"""Read-only source checks. Missing tools are findings, never successful scans."""

import ast
import asyncio
import io
import re
import tempfile
import tokenize
import zipfile
from collections.abc import Callable
from pathlib import Path

from . import sandbox
from .intake import load, unpack
from .models import Evidence, Finding, missing
from .privacy import safe
from .readiness import check_guidance, inventory

CHECKS = {
    "hardcoded_secrets": ("code_security", "gitleaks"),
    "unsafe_patterns": ("code_security", "semgrep"),
    "python_security": ("code_security", "bandit"),
    "dependency_vulnerabilities": ("code_security", "osv"),
    "container_vulnerabilities": ("code_security", "trivy"),
    "prompt_injection_paths": ("injection", "semgrep"),
    "guardrail_path": ("guardrails", "controls"),
    "tool_permissions": ("guardrails", "controls"),
    "pii_logging": ("pii", "controls"),
    "retention": ("pii", "controls"),
    "model_config": ("configuration_reliability", "controls"),
    "timeouts_retries": ("configuration_reliability", "controls"),
    "endpoint_controls": ("configuration_reliability", "controls"),
    "ci_safety": ("configuration_reliability", "controls"),
}


def unverified(bot: int, test: str, reason: str, outcome: str, tool: str = "") -> Finding:
    """A not-tested White Finding that records why, so the UI never has to guess."""
    finding = missing("white", bot, CHECKS[test][0], test, reason)
    finding.details = {"outcome": outcome}
    finding.tool = tool
    action = check_guidance("white", test).get("owner_action")
    if outcome == "insufficient_evidence" and action:
        finding.fix = action
    elif outcome == "missing_input":
        finding.fix = "Supply a valid source ZIP or public repository, then rerun this check."
    elif outcome in ("tool_unavailable", "tool_error"):
        finding.fix = "Install or repair the named scanner, then rerun this check."
    return finding


def _model_literal(literal: str) -> bool:
    """A structured, lower-case model identifier; key prefixes never qualify."""
    return bool(
        re.fullmatch(r"[a-z][a-z0-9]*(?:[./:_-][a-z0-9]+)+", literal)
        and not re.match(r"(?:sk-|gh[opusr]_|xox[baprs]-|AIza|AQ\.)", literal, re.I)
        and (any(character.isdigit() for character in literal) or literal.endswith("-latest"))
    )


def _model_key(name: str) -> bool:
    name = name.lower()
    return name == "model" or name.endswith("_model")


def _model_mapping_entry(line: str) -> bool:
    """Qualify a dict-literal line such as ``"x": {"api_model": "model-1", ...}``.

    Only string literals and ``: , { }`` are allowed, so assignments or code on the same
    line take the normal credential path. Every other string value must look like a
    model name or plain words without digits; anything opaque keeps the alert.
    """
    try:
        tokens = []
        for token in tokenize.generate_tokens(io.StringIO(line.strip()).readline):
            tokens.append(token)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # An unclosed brace at end of a fragment is expected.
    significant = [
        t
        for t in tokens
        if t.type not in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER, tokenize.INDENT)
    ]
    if not significant or any(
        t.type not in (tokenize.STRING, tokenize.OP)
        or (t.type == tokenize.OP and t.string not in ":,{}")
        for t in significant
    ):
        return False
    try:
        values = [
            (ast.literal_eval(significant[i - 2].string), ast.literal_eval(t.string))
            for i, t in enumerate(significant)
            if t.type == tokenize.STRING
            and i >= 2
            and significant[i - 1].string == ":"
            and significant[i - 2].type == tokenize.STRING
        ]
    except (ValueError, SyntaxError):
        return False
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in values):
        return False
    if not any(_model_key(k) and _model_literal(v) for k, v in values):
        return False
    if any(re.search(r"key|secret|token|passw|credential|auth", k, re.I) for k, _ in values):
        return False
    return all(
        not re.match(r"(?:sk-|gh[opusr]_|xox[baprs]-|AIza|AQ\.)", v, re.I)
        and (
            _model_literal(v)
            or re.fullmatch(r"[A-Za-z][A-Za-z_ .()&/'-]*", v)
            or (" " in v and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .()&/'+-]*", v))
        )
        for _, v in values
    )


def _model_assignment(line: str, rule: str) -> bool:
    """Qualify generic model-name matches; never allowlist provider credential rules."""
    if rule != "generic-api-key":
        return False
    try:
        statements = ast.parse(line.strip()).body
    except (SyntaxError, ValueError, RecursionError):
        return _model_mapping_entry(line)
    if len(statements) != 1 or not isinstance(statements[0], (ast.Assign, ast.AnnAssign)):
        return False
    statement = statements[0]
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        return False
    value = statement.value
    if not _model_key(targets[0].id):
        return False
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return False
    # A structured, lower-case name is only context for review, never proof of safety.
    # Key prefixes and opaque/random strings still take the normal credential path.
    return _model_literal(value.value)


def _reported_exact_version(version: object) -> bool:
    """A scanner version is not proof of installation; placeholders cannot match reliably."""
    return bool(
        isinstance(version, str)
        and not re.fullmatch(r"v?0\.0\.0(?:[+_-].*)?", version)
        and not re.search(r"(?:^|[.])[xX](?:[.]|$)", version)
        and re.fullmatch(r"v?\d[0-9A-Za-z.+_-]*", version)
    )


def source_evidence(source: Path, file: str, line: int) -> Evidence:
    relative = file.removeprefix("/source/")
    target = (source / relative).resolve()
    if not target.is_relative_to(source.resolve()) or not target.is_file():
        raise ValueError("Scanner returned an unsafe or missing source path.")
    lines = target.read_text(errors="replace").splitlines()
    snippet = (
        lines[max(0, line - 1)][:4000] if 0 < line <= len(lines) else "No line text available."
    )
    return Evidence(kind="code", file=str(safe(relative)), line=line, excerpt=str(safe(snippet)))


def parse(test: str, output: dict, source: Path, bot: int) -> Finding:
    category, tool = CHECKS[test]
    data = output["data"]
    evidence, hits, control = [], [], None
    details = {
        **{k: output[k] for k in ("image_id", "ruleset")},
        "scanner_completed": True,
        "interpretation_version": "source-evidence-v1",
        **(
            {"database_snapshot": output["database_snapshot"]}
            if "database_snapshot" in output
            else {}
        ),
    }
    review_note = ""

    def unscored(reason: str) -> Finding:
        finding = unverified(bot, test, reason, "insufficient_evidence", tool)
        finding.tool_version = output["version"]
        finding.details = {**details, "outcome": "insufficient_evidence"}
        finding.evidence = evidence
        finding.consequence = "Available scanner evidence is insufficient to score this check; do not treat it as a pass."
        return finding

    if tool == "gitleaks":
        if not isinstance(data, list):
            raise ValueError("Invalid Gitleaks report.")
        qualified = []
        originals = []
        for hit in data:
            item = source_evidence(source, hit["File"], int(hit["StartLine"]))
            # Never persist the secret-containing line, even for an unfamiliar key format.
            path = (source / hit["File"].removeprefix("/source/")).resolve()
            lines = path.read_text(errors="replace").splitlines()
            if not 0 < int(hit["StartLine"]) <= len(lines):
                raise ValueError("Gitleaks returned an invalid source line.")
            line = lines[int(hit["StartLine"]) - 1]
            is_model = _model_assignment(line, str(hit.get("RuleID", "")))
            values = re.findall(r"[\"']([^\"']{8,})[\"']", line)
            tail = values[-1][-4:] if values else "unavailable"
            item.excerpt = (
                "Generic credential rule matched a model-name assignment; credential exposure "
                "is unverified and requires review."
                if is_model
                else "Gitleaks detected a potential credential. Last four characters: " + tail
            )
            original = {
                "file": item.file,
                "line": item.line,
                "rule_id": str(safe(hit.get("RuleID", "unknown"))),
                "classification": "model_context_review" if is_model else "potential_credential",
                "secret": "[REDACTED]",
                "match": "[REDACTED]",
                "scanner_metadata": safe(
                    {
                        key: hit[key]
                        for key in (
                            "RuleID",
                            "Description",
                            "File",
                            "StartLine",
                            "EndLine",
                            "StartColumn",
                            "EndColumn",
                            "Fingerprint",
                            "Entropy",
                            "Tags",
                        )
                        if key in hit
                    }
                ),
            }
            originals.append(original)
            (qualified if is_model else hits).append(original)
            if len(evidence) < 10:
                evidence.append(item)
        details.update(
            raw_findings=originals,
            raw_finding_count=len(data),
            potential_credentials=len(hits),
            model_context_matches=len(qualified),
            raw_retention="Scanner metadata retained; secret and matched source text redacted.",
        )
        if qualified:
            review_note = (
                f" {len(qualified)} generic matches occur in model-name assignments; they are "
                "unverified, not confirmed exposed keys. Review their source context."
            )
            if not hits:
                finding = unscored(review_note.strip())
                finding.fix = "Review the model-name matches; retain real credential alerts."
                return finding
    elif tool == "semgrep":
        if data.get("errors"):
            raise ValueError(
                "Semgrep reported incomplete analysis; inspect scanner installation/rules."
            )
        hits = [
            h
            for h in data.get("results", [])
            if ("untrusted-prompt" in h["check_id"]) == (test == "prompt_injection_paths")
        ]
        evidence = [source_evidence(source, h["path"], int(h["start"]["line"])) for h in hits[:10]]
    elif tool == "bandit":
        if data.get("errors"):
            raise ValueError("Bandit could not parse every selected Python file.")
        if not data.get("metrics", {}).get("_totals", {}).get("loc"):
            return unscored("No Python source was inspected by Bandit.")
        hits = data.get("results", [])
        evidence = [
            source_evidence(source, h["filename"], int(h["line_number"])) for h in hits[:10]
        ]
    elif tool in ("osv", "trivy"):
        if not data.get("results" if tool == "osv" else "Results"):
            return unscored(
                "Scanner found no supported dependency/container targets; no vulnerability pass inferred.",
            )
        if tool == "osv":
            unresolved = []
            raw_advisories = []
            inspected = 0
            for result in data.get("results", []):
                for package in result.get("packages", []):
                    inspected += 1
                    identity = package.get("package", {})
                    exact = _reported_exact_version(identity.get("version"))
                    location = result.get("source", {})
                    if not exact:
                        unresolved.append({"package": identity, "source": location})
                    for vuln in package.get("vulnerabilities", []):
                        advisory = {
                            "id": vuln.get("id"),
                            "package": identity,
                            "source": location,
                            "scanner_advisory": vuln,
                            "version_status": "reported_exact" if exact else "unresolved",
                        }
                        raw_advisories.append(advisory)
                        if exact:
                            hits.append(advisory)
            details.update(
                raw_findings=safe(raw_advisories),
                raw_finding_count=len(raw_advisories),
                exact_version_advisories=len(hits),
                unresolved_packages=safe(unresolved),
                installed_versions_verified=False,
                raw_retention="Advisory content and package/source metadata retained with privacy redaction.",
            )
            evidence = [
                Evidence(
                    kind="tool",
                    excerpt=str(safe({k: v for k, v in h.items() if k != "scanner_advisory"}))[
                        :4000
                    ],
                    source_id=tool,
                )
                for h in raw_advisories[:10]
            ]
            if not inspected:
                return unscored(
                    "Scanner reported no inspected packages; no vulnerability pass inferred."
                )
            if unresolved:
                review_note = (
                    f" {len(unresolved)} package versions are unresolved or placeholders. "
                    "Their advisory candidates are not confirmed installed vulnerabilities. "
                    "Provide a lockfile or resolved dependency inventory and rerun."
                )
                if not hits:
                    finding = unscored(review_note.strip())
                    finding.fix = "Provide a lockfile or resolved inventory with exact versions."
                    return finding
        else:
            for result in data.get("Results", []):
                hits.extend(
                    {"id": v.get("VulnerabilityID"), "package": v.get("PkgName")}
                    for v in result.get("Vulnerabilities", [])
                )
                hits.extend(
                    {"id": v.get("ID"), "package": result.get("Target")}
                    for v in result.get("Misconfigurations", [])
                    if v.get("Status") == "FAIL"
                )
            evidence = [
                Evidence(kind="tool", excerpt=str(safe(str(h))), source_id=tool) for h in hits[:10]
            ]
    else:
        if not data.get("files"):
            return unscored("No supported source files were inspected.")
        hits = data.get("hits", {}).get(test, [])
        observed = data.get("observations", {}).get(test, [])
        if observed or "observations" in data:
            details.update(
                source_observations=safe(observed[:10]),
                python_files_parsed=data.get("python_files_parsed", 0),
                python_parse_errors=safe(data.get("python_parse_errors", [])[:10]),
                observation_note="Structured source declarations; not runtime behavior.",
            )
        if test == "endpoint_controls" and any(
            o.get("kind") == "upstream_rate_limit_handler" for o in observed
        ):
            review_note = (
                " Upstream provider rate-limit handlers were found; they do not limit or "
                "authenticate incoming requests."
            )
        if not hits:
            reason = (
                "No matching control evidence found by these limited text rules; "
                "absence is not proven."
            )
            if observed:
                reason += " Source parsing observed: " + "; ".join(
                    f"{o['kind'].replace('_', ' ')}"
                    + (f" ({o['value']})" if "value" in o else "")
                    + f" at {o['file']}:{o['line']}"
                    for o in observed[:3]
                )
                reason += ". These are declarations, not runtime proof."
            return unscored(str(safe(reason)) + review_note)
        evidence = [source_evidence(source, h["file"], h["line"]) for h in hits[:10]]
        control = test not in ("pii_logging", "model_config")
    # A successful scan is scoped to its rules, not universal security coverage.
    if not evidence:
        evidence = [
            Evidence(
                kind="tool",
                excerpt="Scanner completed; no matches in its selected rules.",
                source_id=output["image_id"],
            )
        ]
    verdict = "exists" if control else "fail" if hits else "pass"
    severity = (
        "Critical"
        if hits and test == "hardcoded_secrets"
        else ("High" if verdict == "fail" else "Pass" if verdict == "pass" else "Low")
    )
    if tool == "bandit" and hits:
        severity = max(
            (str(h.get("issue_severity", "HIGH")).title() for h in hits),
            key=lambda value: {"Low": 1, "Medium": 2, "High": 3}.get(value, 3),
        )
    reason = (
        "A control declaration exists. Its response path and effectiveness require a behavior test."
        if control
        else f"{len(hits)} scanner findings in this rule set."
        if hits
        else "No findings in the completed scanner's rules; other risks may remain."
    )
    if tool == "osv" and hits:
        reason = (
            f"{len(hits)} advisories match scanner-reported exact dependency versions. "
            "Source scanning does not verify versions deployed in a running system."
        )
    reason += review_note
    return Finding(
        mode="white",
        bot=bot,
        category=category,
        test_id=test,
        verdict=verdict,
        severity=severity,
        confidence="Low" if control else "Medium",
        evidence=evidence,
        explanation=reason,
        checked=test.replace("_", " "),
        control=control,
        consequence="Exposed credentials, unsafe operations or missing safeguards can affect users.",
        fix="Review the cited lines, apply least privilege and test the behavior after correction.",
        tool=tool,
        tool_version=output["version"],
        details=details,
        review=bool(review_note),
    )


class WhiteEngine:
    def __init__(self, on_progress: Callable[[list[Finding]], None] | None = None):
        self.on_progress = on_progress

    def required_inputs(self) -> dict[str, list[str]]:
        return {test: ["code", "Docker", tool] for test, (_, tool) in CHECKS.items()}

    def plan(self, inputs: dict) -> list[dict]:
        return [
            {
                "test": test,
                "category": category,
                "tool": tool,
                "code": inputs.get("code", ""),
                "bot": inputs.get("bot", 0),
            }
            for test, (category, tool) in CHECKS.items()
        ]

    async def run(self, plan: list[dict]) -> list[Finding]:
        if not plan:
            return []
        bot, ident = plan[0]["bot"], plan[0]["code"]
        if not ident:
            return [
                unverified(
                    bot,
                    row["test"],
                    "Upload a source ZIP or import a GitHub repository.",
                    "missing_input",
                )
                for row in plan
            ]
        try:
            archive, _ = load(ident, "code")
            with tempfile.TemporaryDirectory(prefix="studio-source-") as folder:
                # Keep the private parent 0700 while the mounted child is readable
                # by the unprivileged scanner UID on Linux/macOS as well.
                source = Path(folder) / "source"
                source.mkdir(mode=0o755)
                await asyncio.to_thread(unpack, archive.read_bytes(), source)
                # Uploaded ignore files must not disable the Studio's trusted rules.
                for path in source.rglob("*"):
                    if path.is_file() and path.name in {
                        ".semgrepignore",
                        ".gitignore",
                        ".bandit",
                        ".gitleaksignore",
                        ".trivyignore",
                        ".trivyignore.yaml",
                    }:
                        if path.resolve().is_relative_to(source.resolve()):
                            path.unlink()
                for path in [source, *source.rglob("*")]:
                    path.chmod(0o755 if path.is_dir() else 0o644)
                if not any(p.is_file() for p in source.rglob("*")):
                    return [
                        unverified(
                            bot,
                            r["test"],
                            "Source archive contains no files to scan.",
                            "missing_input",
                        )
                        for r in plan
                    ]
                tools = {}
                results = []
                try:
                    files = await asyncio.to_thread(inventory, archive)
                except (ValueError, OSError, zipfile.BadZipFile):
                    files = None
                summary = (
                    {
                        "lockfiles": files["lockfiles"][:20],
                        "requirements_files": files["requirements"][:20],
                        "container_configs": files["container_configs"][:20],
                        "exact_packages": len(files["exact_packages"]),
                        "unresolved_packages": files["unresolved_packages"][:50],
                        "note": "Supplied files only; not proof of deployed versions.",
                    }
                    if files
                    else None
                )
                # Keep memory bounded on modest hardware; parallel engines, serial scanner tools.
                for tool in dict.fromkeys(row["tool"] for row in plan):
                    try:
                        tools[tool] = await sandbox.scan(tool, source)
                    except sandbox.ToolUnavailable as exc:
                        tools[tool] = str(exc)
                    batch = []
                    for row in [r for r in plan if r["tool"] == tool]:
                        output = tools[tool]
                        if isinstance(output, str):
                            batch.append(
                                unverified(bot, row["test"], output, "tool_unavailable", tool)
                            )
                            continue
                        try:
                            batch.append(parse(row["test"], output, source, bot))
                        except (ValueError, KeyError, TypeError) as exc:
                            batch.append(unverified(bot, row["test"], str(exc), "tool_error", tool))
                    for finding in batch:
                        if summary and finding.test_id in (
                            "dependency_vulnerabilities",
                            "container_vulnerabilities",
                        ):
                            finding.details["inventory"] = summary
                    results.extend(batch)
                    if self.on_progress:
                        self.on_progress(batch)
                indexed = {f.test_id: f for f in results}
                return [indexed[r["test"]] for r in plan]
        except (ValueError, OSError) as exc:
            return [
                unverified(
                    bot, row["test"], type(exc).__name__ + ": input unavailable.", "missing_input"
                )
                for row in plan
            ]
