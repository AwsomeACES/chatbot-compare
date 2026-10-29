"""Preflight readiness and post-run evidence status.

Readiness says whether a check is eligible to attempt; it is never a pass. Outcome
classification explains a recorded Finding without changing its verdict, score or
evidence, so historical runs keep their original results and only gain explanation.
"""

import asyncio
import json
import re
import zipfile
from html import escape
from pathlib import Path, PurePosixPath

from ..config import ROOT
from . import sandbox
from .intake import load
from .privacy import safe

GUIDANCE_FILE = ROOT / "app/studio/evidence-guidance.json"
GENERIC_FIX = "Supply the missing input or install the named tool, then rerun this check."
# Files Trivy/OSV can resolve to exact versions. requirements.txt only counts when pinned.
LOCKFILES = {
    "poetry.lock",
    "uv.lock",
    "pipfile.lock",
    "pdm.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.sum",
    "cargo.lock",
    "gemfile.lock",
    "composer.lock",
}
MANIFESTS = {"pyproject.toml", "pipfile", "package.json", "setup.py", "setup.cfg", "go.mod"}
CONTAINER_CONFIG = re.compile(
    r"(?:^|/)(?:dockerfile[^/]*|containerfile|(?:docker-)?compose[^/]*\.ya?ml)$", re.I
)
REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(===?|[<>~!]=?)?\s*(\S*)"
)
INVENTORY_BYTES = 256 * 1024
MODE_NAMES = {
    "black": "Black-box testing",
    "gray": "Gray-box testing",
    "white": "White-box testing",
}


def guidance() -> dict:
    """Load the editable guidance catalogue."""
    return json.loads(GUIDANCE_FILE.read_text(encoding="utf-8"))


def check_guidance(mode: str, test_id: str, catalogue: dict | None = None) -> dict:
    """Guidance for one check; Gray rule variants such as declared_behavior-2 share a base."""
    checks = (catalogue or guidance())["checks"].get(mode, {})
    base = re.sub(r"-\d+$", "", test_id)
    return checks.get(test_id) or checks.get(base) or checks.get("_default", {})


def _requirements(text: str) -> tuple[list[str], list[str]]:
    exact, unresolved = [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http:", "https:")):
            continue
        match = REQUIREMENT.match(line)
        if not match:
            continue
        name, _, operator, version = match.groups()
        pinned = operator in ("==", "===") and "*" not in version and bool(version)
        (exact if pinned else unresolved).append(name.lower())
    return exact, unresolved


def inventory(archive: Path) -> dict:
    """List an uploaded ZIP without extracting or executing it.

    Only small dependency text files are read, as text. The result is a description of
    supplied files, not proof of what is deployed.
    """
    result = {
        "files": 0,
        "python_files": 0,
        "workflows": [],
        "lockfiles": [],
        "manifests": [],
        "container_configs": [],
        "requirements": [],
        "exact_packages": [],
        "unresolved_packages": [],
        "packages": [],
    }
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            if item.is_dir():
                continue
            name = item.filename.replace("\\", "/")
            path = PurePosixPath(name)
            lower = path.name.lower()
            result["files"] += 1
            if lower.endswith(".py"):
                result["python_files"] += 1
            if re.search(r"(?:^|/)\.github/workflows/[^/]+\.ya?ml$", name, re.I):
                result["workflows"].append(name)
            if lower in LOCKFILES:
                result["lockfiles"].append(name)
            elif lower in MANIFESTS:
                result["manifests"].append(name)
            if CONTAINER_CONFIG.search(name):
                result["container_configs"].append(name)
            if re.fullmatch(r"requirements[^/]*\.(?:txt|in)", lower):
                result["requirements"].append(name)
                if item.file_size <= INVENTORY_BYTES:
                    text = bundle.read(item).decode("utf-8", errors="replace")
                    exact, unresolved = _requirements(text)
                    result["exact_packages"] += exact
                    result["unresolved_packages"] += unresolved
                    result["packages"] += [["PyPI", name] for name in exact + unresolved]
            elif lower == "package-lock.json" and item.file_size <= INVENTORY_BYTES:
                try:
                    data = json.loads(bundle.read(item).decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                packages = data.get("packages") or {}
                names = [
                    key.rsplit("node_modules/", 1)[-1]
                    for key, value in packages.items()
                    if key and isinstance(value, dict) and value.get("version")
                ]
                result["exact_packages"] += names
                result["packages"] += [["npm", name] for name in names]
    for key in ("exact_packages", "unresolved_packages"):
        result[key] = sorted(set(result[key]))
    result["packages"] = sorted({tuple(item) for item in result["packages"]})
    result["packages"] = [list(item) for item in result["packages"]]
    return safe(result)


async def tool_status(tools: list[str]) -> dict[str, str]:
    """Return an empty string for a ready tool, otherwise the reason it is unavailable.

    Inspects local images and offline databases only; never pulls or updates them.
    """
    try:
        sandbox.docker_prefix()
    except sandbox.ToolUnavailable as exc:
        return {tool: str(exc) for tool in tools}
    spec = sandbox.specification()["tools"]

    async def one(tool: str) -> str:
        item = spec[tool]
        try:
            rc, output = await sandbox.bounded_process(
                ["docker", "image", "inspect", item["image"], "--format={{.Id}}"], 30, 4096
            )
        except (OSError, TimeoutError, sandbox.ToolUnavailable) as exc:
            return f"{tool} image could not be inspected ({type(exc).__name__})."
        if rc != 0 or not output.strip().startswith(b"sha256:"):
            return (
                f"Pinned {tool} {item['version']} image is not installed; automatic pulls "
                "are disabled."
            )
        if item.get("database"):
            database = sandbox.database_path(item["database"])
            if not database.is_dir() or not any(database.iterdir()):
                return f"Offline {tool} database is missing; provision it before scanning."
        return ""

    results = await asyncio.gather(*(one(tool) for tool in tools))
    return dict(zip(tools, results, strict=True))


def osv_coverage(packages: list[str]) -> str:
    """Name packages outside a scoped OSV snapshot; empty when unscoped or covered."""
    root = sandbox.database_path("osv")
    manifest = root / "scope.json"
    if not packages or not manifest.is_file():
        return ""
    try:
        scope = json.loads(manifest.read_text(encoding="utf-8"))
        covered = {re.sub(r"[-_.]+", "-", name).lower() for _, name in scope["packages"]}
    except (ValueError, KeyError, TypeError, OSError):
        return "The offline OSV snapshot has an unreadable coverage manifest."
    outside = sorted(p for p in packages if re.sub(r"[-_.]+", "-", p).lower() not in covered)
    if not outside:
        return ""
    names = ", ".join(outside[:8]) + (" and more" if len(outside) > 8 else "")
    return f"The offline OSV snapshot does not cover {len(outside)} listed packages: {names}."


def _white_row(test: str, tool: str, files: dict | None, tools: dict, notes: dict) -> dict:
    """Readiness for one White check from the archive inventory and tool status."""
    if files is None:
        return {
            "status": "needs_input",
            "reason": "No source ZIP or repository was supplied.",
            "next_action": "Upload a source ZIP or import a public GitHub repository.",
        }
    if tools.get(tool):
        return {
            "status": "tool_unavailable",
            "reason": tools[tool],
            "next_action": "Install the pinned scanner image or offline database (see the "
            "assurance guide), then check readiness again.",
        }
    exact, unresolved = files["exact_packages"], files["unresolved_packages"]
    has_lock = bool(files["lockfiles"])
    if test == "python_security" and not files["python_files"]:
        return {
            "status": "not_applicable",
            "reason": "The archive has no Python files. Bandit only reviews Python.",
            "next_action": "No action for a non-Python bot.",
        }
    if test == "dependency_vulnerabilities":
        if not (has_lock or files["requirements"] or files["manifests"]):
            return {
                "status": "needs_input",
                "reason": "No dependency manifest or lockfile was found in the archive.",
                "next_action": "Add the lockfile or a pinned dependency list to the ZIP.",
            }
        if not has_lock and not exact:
            return {
                "status": "needs_input",
                "reason": "Dependencies are listed without exact versions, so advisories "
                "cannot be matched to installed versions.",
                "next_action": "Add a lockfile or pin versions with == (for example from "
                "pip freeze).",
            }
        if notes.get("osv"):
            return {
                "status": "tool_unavailable",
                "reason": notes["osv"],
                "next_action": "Provision an OSV snapshot that covers every listed package.",
            }
        if unresolved:
            return {
                "status": "ready",
                "reason": f"{len(unresolved)} listed packages have no exact version and "
                "will stay unresolved.",
                "next_action": "Pin the remaining versions for a complete result.",
            }
    if test == "container_vulnerabilities" and not (
        has_lock or exact or files["container_configs"]
    ):
        return {
            "status": "needs_input",
            "reason": "No lockfile, pinned requirements or container configuration that "
            "Trivy supports was found.",
            "next_action": "Add the lockfile and the Dockerfile used for deployment. Studio "
            "does not build or scan uploaded images.",
        }
    if test == "ci_safety" and not files["workflows"]:
        return {
            "status": "needs_input",
            "reason": "The archive has no .github/workflows files.",
            "next_action": "Include the CI workflow files and share a run link for the "
            "tested commit.",
        }
    return {
        "status": "ready",
        "reason": "Input and tool are available.",
        "next_action": "Start the test.",
    }


async def preflight(modes: list[str], inputs: list[dict], targets: list[dict]) -> dict:
    """Describe every check the selected modes would plan, before anything runs."""
    from .gray import CHECKS as GRAY
    from .white import CHECKS as WHITE

    catalogue = guidance()
    labels = catalogue["statuses"]
    rows = []
    inventories: list[dict | None] = []
    for fields in inputs:
        files = None
        if "white" in modes and fields.get("code"):
            try:
                archive, _ = load(fields["code"], "code")
                files = await asyncio.to_thread(inventory, archive)
            except (ValueError, OSError, zipfile.BadZipFile):
                files = None
        inventories.append(files)
    tools = {}
    notes = {}
    if any(files is not None for files in inventories):
        tools = await tool_status(list(dict.fromkeys(tool for _, tool in WHITE.values())))

    def add(mode: str, bot: int, test: str, state: dict) -> None:
        info = check_guidance(mode, test, catalogue)
        rows.append(
            {
                "mode": mode,
                "bot": bot,
                "test_id": test,
                "title": info.get("title", test.replace("_", " ")),
                "status": state["status"],
                "status_label": labels[state["status"]],
                "reason": state["reason"],
                "next_action": state["next_action"],
                "source_scope": info.get("source_scope", ""),
                "best_outcome": state.get("best_outcome", ""),
            }
        )

    for bot, fields in enumerate(inputs):
        if "white" in modes:
            files = inventories[bot]
            notes = (
                {"osv": osv_coverage(files["exact_packages"] + files["unresolved_packages"])}
                if files
                else {}
            )
            for test, (_, tool) in WHITE.items():
                state = _white_row(test, tool, files, tools, notes)
                if tool == "controls" and state["status"] == "ready":
                    state["best_outcome"] = (
                        "Declaration found at most. Source text cannot show that a control works."
                    )
                add("white", bot, test, state)
        if "gray" in modes:
            for test, (_, kinds) in GRAY.items():
                supplied = all(fields.get(kind) for kind in kinds)
                add(
                    "gray",
                    bot,
                    test,
                    {
                        "status": "ready" if supplied else "needs_input",
                        "reason": "The private input is supplied."
                        if supplied
                        else f"Needs the {', '.join(k.replace('_', ' ') for k in kinds)} input.",
                        "next_action": "Start the test."
                        if supplied
                        else "Upload that file on this bot's card.",
                    },
                )
    if "black" in modes:
        for bot, target in enumerate(targets):
            reachable = bool(target.get("url") or target.get("archive_id"))
            add(
                "black",
                bot,
                "conversation",
                {
                    "status": "ready" if reachable else "needs_input",
                    "reason": "A chat link or API endpoint is set."
                    if reachable
                    else "No chat link or API endpoint is set.",
                    "next_action": "Start the test. Ready does not mean the bot is online."
                    if reachable
                    else "Add the bot's chat link or API endpoint.",
                },
            )
    counts = {key: sum(r["status"] == key for r in rows) for key in labels}
    return {
        "version": catalogue["version"],
        "checks": rows,
        "counts": counts,
        "notice": "Ready means the check can be attempted. It is not a pass.",
    }


def outcome(finding: dict) -> str:
    """Classify why a Finding has its verdict. Older records are inferred conservatively."""
    recorded = finding.get("details", {}).get("outcome")
    verdict = finding["verdict"]
    original = finding.get("original_finding") or {}
    if finding.get("overridden"):
        if verdict == "pass" and original.get("verdict") not in (None, "pass"):
            return "review_cleared"
        if verdict == "fail":
            return "confirmed_defect"
    if verdict == "pass":
        return "measured_pass"
    if verdict == "fail":
        return "flagged"
    if verdict == "exists":
        return "declaration"
    if recorded:
        return recorded
    text = finding.get("explanation", "").lower()
    if text == "pending execution." or "stopped" in text or "interrupted" in text:
        return "not_attempted"
    if finding.get("details", {}).get("scanner_completed"):
        return "insufficient_evidence"
    if "engine error" in text or "could not finish" in text or "invalid" in text:
        return "tool_error"
    if finding.get("tool") and any(
        word in text for word in ("unavailable", "not installed", "missing", "does not match")
    ):
        return "tool_unavailable"
    if any(word in text for word in ("upload", "input unavailable", "no files", "supply")):
        return "missing_input"
    return "unverified"


def supplemental(run: dict) -> dict:
    """The saved assistant review, else the latest accepted automated explanation."""
    if run.get("ai_source_review"):
        return run["ai_source_review"]
    for item in reversed(run.get("ai_explanations", [])):
        if item.get("status") == "accepted":
            attempts = "; ".join(
                f"{a.get('model', '')}: {a.get('status', '')}" for a in item.get("attempts", [])
            )
            return {
                **item,
                "model": f"{item['source']} by {item.get('model', 'unknown model')}",
                "automation_status": attempts,
            }
    return {}


def explanation_provenance(run: dict) -> dict:
    """Where an optional AI explanation came from, which attempts failed and what it cost.

    One block, rendered identically by the JSON, PDF and teammate exports, so the three never
    disagree about whether an explanation exists or who produced it. Recorded Findings, verdicts
    and reviews are never changed by an explanation.
    """
    review = supplemental(run)
    attempts = []
    for item in run.get("ai_explanations", []):
        for attempt in item.get("attempts", []):
            attempts.append(
                {
                    "model": attempt.get("model", "Not recorded"),
                    "local": attempt.get("local"),
                    "returned_model": attempt.get("provider_model", "Not supplied"),
                    "status": attempt.get("status", "Not recorded"),
                    "reason": attempt.get("reason", ""),
                }
            )
    failures = [a for a in attempts if a["status"] != "accepted"]
    if not review:
        return {
            "present": False,
            "note": "No optional AI explanation is attached. Recorded Findings are unchanged.",
            "attempts": attempts,
            "provider_failures": failures,
            "cost": explanation_cost(run),
        }
    return {
        "present": True,
        "source": review.get("source", "Not recorded"),
        "model": review.get("model", "Not recorded"),
        "returned_model": review.get("provider_model", "Not supplied"),
        "local": review.get("local"),
        "cloud_consent": review.get("cloud_consent"),
        "payload_hash": review.get("payload_hash", ""),
        "checks_reviewed": len(review.get("checks", [])),
        "automation_status": review.get("automation_status", ""),
        "attempts": attempts,
        "provider_failures": failures,
        "cost": explanation_cost(run),
        "note": (
            review.get("purpose")
            or "Supplemental explanation. Original verdicts, severity and reviews are unchanged."
        ),
    }


def explanation_cost(run: dict) -> dict:
    """Metered cost of explanation calls. Unknown billing stays Unknown, never zero."""
    from ..blackbox import metering
    from ..blackbox.cost_summary import totals

    rows = [
        row
        for row in metering.events(run["id"])
        if (row.get("test_case_id") or "") == "white-ai-explanation"
    ]
    if not rows:
        return {"status": "No explanation calls", "calls": 0}
    summary = totals(rows)
    return {"status": summary.get("status", "Unknown"), "calls": len(rows), "totals": summary}


def scanner_state(run: dict, finding: dict) -> dict:
    """Whether the tool ran, reported separately from what the check concluded.

    A scanner finishing is not a result. Six tools completed on the VoltKart source and eleven
    checks still had no evidence, so execution status and check outcome are shown apart.
    """
    engine = (run.get("engine_status") or {}).get(finding["mode"], "unknown")
    details = finding.get("details") or {}
    completed = details.get("scanner_completed")
    if completed is None:
        completed = engine == "completed" and finding["verdict"] != "tool_error"
    return {
        "tool": finding.get("tool", "") or "none recorded",
        "version": finding.get("tool_version", "") or "not recorded",
        "engine_status": engine,
        "executed": bool(completed),
        "note": "The scanner ran and returned a report. That is separate from the check outcome: "
        "a completed scanner with no supported target, or with no rule for this control, is not "
        "a pass."
        if completed
        else "The scanner did not produce a usable report, so this check has no result from it.",
    }


def coverage_statement(counts: dict) -> dict:
    """Say plainly what the measured results do and do not establish."""
    return {
        "measured_of_planned": f"{counts['measured']} of {counts['planned']}",
        "statement": (
            f"{counts['passed']} of {counts['planned']} checks passed and "
            f"{counts['unverified']} produced no evidence. A passing check means one tool's rules "
            "found nothing of their kind in the supplied source. Most of this assessment is "
            "therefore unverified rather than clean, and the passes do not add up to a secure "
            "application."
        ),
        "what_a_pass_means": (
            "One named tool, at the recorded version, applied its own rules to the uploaded "
            "source and reported no match. It is a statement about those rules on that source, "
            "not about the running application."
        ),
        "what_is_not_established": [
            "Runtime behaviour: source scanning cannot show what the deployed application does.",
            "Effectiveness of any control that is only declared in source; a declaration is not "
            "behavioural evidence.",
            "Absence of a weakness for which no rule exists, including logic and design flaws.",
            "Anything outside the uploaded source, such as infrastructure, configuration held "
            "elsewhere, or a dependency resolved only at deployment.",
            "Vulnerabilities in dependency versions that could not be resolved; an unresolved "
            "version is unverified, never a confirmed installed vulnerable version.",
        ],
        "note": "This is a coverage statement, not a certification or a legal finding.",
    }


def evidence_status(run: dict) -> dict:
    """Counts and per-check guidance for a saved run, derived without mutating it."""
    catalogue = guidance()
    outcomes, causes = catalogue["outcomes"], catalogue["causes"]
    review = supplemental(run)
    reviewed = {item.get("test_id"): item for item in review.get("checks", [])}
    rows = []
    for finding in run.get("findings", []):
        code = outcome(finding)
        meta = outcomes.get(code, outcomes["unverified"])
        info = check_guidance(finding["mode"], finding["test_id"], catalogue)
        cause = meta["cause"]
        if code == "insufficient_evidence" and info.get("gap"):
            cause = info["gap"]
        unresolved = code not in ("measured_pass", "review_cleared")
        rows.append(
            {
                "key": f"{finding['bot']}:{finding['mode']}:{finding['test_id']}",
                "mode": finding["mode"],
                "bot": finding["bot"],
                "test_id": finding["test_id"],
                "title": info.get("title", finding["test_id"].replace("_", " ")),
                "verdict": finding["verdict"],
                "original_verdict": (finding.get("original_finding") or {}).get(
                    "verdict", finding["verdict"]
                ),
                "outcome": code,
                "outcome_label": meta["label"],
                "cause": cause,
                "cause_label": causes.get(cause, cause),
                "why": info.get("why_unverified", meta["text"])
                if code == "insufficient_evidence"
                else meta["text"],
                "recorded_reason": finding.get("explanation", ""),
                "scanner": scanner_state(run, finding),
                "source_scope": info.get("source_scope", ""),
                "required_evidence": info.get("required_evidence", []) if unresolved else [],
                "owner_action": info.get("owner_action", "") if unresolved else "",
                "next_test": info.get("next_test", "") if unresolved else "",
                "unresolved": unresolved,
                "supplemental_review": {
                    "source": review.get("model", "AI source review"),
                    "assessment": reviewed[finding["test_id"]].get("assessment", ""),
                    "explanation": reviewed[finding["test_id"]].get("explanation", ""),
                    "note": "Supplemental explanation; the recorded verdict is unchanged.",
                }
                if finding["mode"] == "white" and finding["test_id"] in reviewed
                else None,
            }
        )
    findings = run.get("findings", [])
    counts = {
        "planned": len(findings),
        "processed": sum(
            r["outcome"]
            in (
                "measured_pass",
                "flagged",
                "confirmed_defect",
                "review_cleared",
                "declaration",
                "insufficient_evidence",
                "tool_error",
            )
            for r in rows
        ),
        "measured": sum(f["verdict"] in ("pass", "fail") for f in findings),
        "passed": sum(f["verdict"] == "pass" for f in findings),
        "failed": sum(f["verdict"] == "fail" for f in findings),
        "declarations": sum(f["verdict"] == "exists" for f in findings),
        "unverified": sum(f["verdict"] == "not_tested" for f in findings),
        "human_review": sum(bool(f.get("review")) and not f.get("overridden") for f in findings),
        "reviewed": sum(bool(f.get("overridden")) for f in findings),
    }
    by_outcome: dict[str, int] = {}
    for row in rows:
        by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + 1
    return {
        "version": catalogue["version"],
        "counts": counts,
        "by_outcome": by_outcome,
        "checks": rows,
        "coverage": coverage_statement(counts),
        "notice": "Processed means the check ran. Only Passed and Needs attention are measured "
        "results. Declarations and unverified checks are not passes.",
        "historical_note": "Explanations are added to the original results. No check was "
        "re-run and no saved verdict was changed.",
    }


def teammate_markdown(run: dict) -> str:
    """A short, shareable list of unresolved checks. Untrusted text is HTML-escaped."""
    status = run.get("evidence_status") or evidence_status(run)
    counts = status["counts"]

    def text(value: object) -> str:
        return escape(str(value), quote=False).replace("\n", " ")

    names = {
        index: target.get("name") or f"Bot {index + 1}"
        for index, target in enumerate(run.get("config", {}).get("targets", []))
    }
    lines = [
        "# AI Agent Studio: evidence still needed",
        "",
        f"Test `{text(run['id'])}` · {text(run.get('status', ''))} · "
        f"{text(', '.join(MODE_NAMES.get(m, m) for m in run.get('modes', [])))}",
        "",
        f"- Checks planned: {counts['planned']}; processed: {counts['processed']}",
        f"- Measured results: {counts['measured']} ({counts['passed']} passed, "
        f"{counts['failed']} need attention)",
        f"- Declarations only: {counts['declarations']}; not verified: {counts['unverified']}",
        f"- Waiting for human review: {counts['human_review']}",
        "",
        text(status["notice"]),
        "",
        text(status["historical_note"]),
        "",
        "## What these results establish",
        "",
        text(status["coverage"]["statement"]),
        "",
        f"- A passing check means: {text(status['coverage']['what_a_pass_means'])}",
        *(
            f"- Not established: {text(item)}"
            for item in status["coverage"]["what_is_not_established"]
        ),
        "",
        text(status["coverage"]["note"]),
        "",
        "## Checks to resolve",
        "",
    ]
    explanation = run.get("ai_explanation_provenance") or explanation_provenance(run)
    provenance_lines = ["## Optional AI explanation", ""]
    if explanation["present"]:
        provenance_lines += [
            f"- Source: {text(explanation['source'])}",
            f"- Model: {text(explanation['model'])} "
            f"(returned {text(explanation['returned_model'])}; a returned name is not a "
            "guaranteed immutable revision)",
            f"- Local judge: {text(explanation['local'])}; cloud consent: "
            f"{text(explanation['cloud_consent'])}",
            f"- Checks reviewed: {text(explanation['checks_reviewed'])}",
            f"- {text(explanation['note'])}",
        ]
    else:
        provenance_lines.append(f"- {text(explanation['note'])}")
    for failure in explanation["provider_failures"]:
        provenance_lines.append(
            f"- Provider attempt {text(failure['model'])}: {text(failure['status'])}"
            + (f" — {text(failure['reason'])}" if failure["reason"] else "")
        )
    cost = explanation["cost"]
    provenance_lines += [
        f"- Explanation cost: {text(cost['status'])} ({text(cost['calls'])} call(s))",
        "",
    ]
    unresolved = [row for row in status["checks"] if row["unresolved"]]
    if not unresolved:
        lines.append("No unresolved checks.")
    for row in unresolved:
        bot = names.get(row["bot"], "Bot " + str(row["bot"] + 1))
        lines += [
            f"### {text(row['title'])} (`{text(row['test_id'])}`)",
            "",
            f"- Bot: {text(bot)} · {text(MODE_NAMES.get(row['mode'], row['mode']))}",
            f"- Result: {text(row['outcome_label'])} (recorded verdict: "
            f"{text(row['original_verdict'])})",
            f"- Reason type: {text(row['cause_label'])}",
            f"- Why: {text(row['why'])}",
            f"- Recorded finding: {text(row['recorded_reason'])}",
        ]
        extra = row.get("supplemental_review")
        if extra:
            lines.append(
                f"- Supplemental {text(extra['source'])}: "
                f"{text(extra['assessment'].replace('_', ' '))}. {text(extra['explanation'])} "
                f"({text(extra['note'])})"
            )
        if row["required_evidence"]:
            lines.append("- Evidence needed: " + "; ".join(map(text, row["required_evidence"])))
        if row["owner_action"]:
            lines.append(f"- Owner action: {text(row['owner_action'])}")
        if row["next_test"]:
            lines.append(f"- Next test: {text(row['next_test'])}")
        lines.append("")
    return "\n".join(lines + provenance_lines).rstrip() + "\n"
