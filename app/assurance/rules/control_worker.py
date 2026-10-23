"""Trusted text and syntax scanner run ONLY inside the read-only, networkless container.

No uploaded modules/config are imported or executed. Python files are parsed with
``ast.parse`` only. Positive matches establish declarations, never their effectiveness
or complete dataflow; absence of a match is never proof that a control is missing.
"""

import ast
import json
import re
import sys
from pathlib import Path

RULES = {
    "guardrail_path": (
        "guardrails",
        r"(?:return|response|answer).{0,80}(?:guardrail|moderate|validate_output)|(?:guardrail|moderate|validate_output)\s*\(",
        "A guardrail call is declared; only a failed/passed chat can establish effectiveness.",
    ),
    "tool_permissions": (
        "guardrails",
        r"allowlist|allowed_tools|require_confirmation|human_approval",
        "Tool permission or confirmation control is declared.",
    ),
    "pii_logging": (
        "pii",
        r"(?:logger\.|logging\.|console\.log).{0,100}(?:email|phone|password|api_key|request\.body)",
        "A logging statement references potentially private data; review redaction.",
    ),
    "retention": (
        "pii",
        r"retention_days|expire_after|delete_after|ttl_seconds",
        "A retention control is declared; expiry behavior is not proven.",
    ),
    "model_config": (
        "configuration_reliability",
        r"(?:model|model_name).{0,30}latest",
        "An unpinned latest model alias can change between runs.",
    ),
    "timeouts_retries": (
        "configuration_reliability",
        r"timeout\s*[:=]|max_retries\s*[:=]|fallback\s*[:=]",
        "Timeout, retry or fallback setting is declared.",
    ),
    "endpoint_controls": (
        "configuration_reliability",
        r"rate_limit|ratelimit|limiter\.|require_auth|HTTPBearer|authenticate",
        "An endpoint access or rate control is declared; coverage is not proven.",
    ),
    "ci_safety": (
        "configuration_reliability",
        r"(?:pytest|promptfoo|deepeval|garak).{0,100}(?:safety|guardrail|injection)|(?:safety|guardrail|injection).{0,100}(?:pytest|promptfoo|deepeval|garak)",
        "A CI command names safety tests; a green CI run is still needed.",
    ),
}
EXTENSIONS = {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".sh"}
# Catching an upstream provider's quota error is not inbound request limiting.
UPSTREAM_ERROR = re.compile(r"(?:RateLimit|Quota|TooManyRequests)\w*(?:Error|Exception)")
INBOUND = re.compile(r"auth|user|token|bearer|api_key|session|limit", re.I)
SESSION_STORE = re.compile(r"session|history|conversation|memory", re.I)
MODEL_NAME = re.compile(r"[a-z][a-z0-9]*(?:[./:_-][a-z0-9]+)+")
CREDENTIAL = re.compile(r"(?:sk-|gh[opusr]_|xox[baprs]-|AIza|AQ\.)", re.I)
MAX_ITEMS = 10
MAX_PYTHON_BYTES = 1024 * 1024


def dotted(node: ast.AST) -> str:
    """Name of a call target or decorator, such as ``limiter.limit``."""
    if isinstance(node, ast.Call):
        return dotted(node.func)
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def literal(node: ast.AST | None) -> object:
    """A constant value only; expressions are reported as unresolved, never evaluated."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
        return node.value
    return None


def model_name(value: str) -> str:
    """Report only recognizable model identifiers; never echo other string literals."""
    if MODEL_NAME.fullmatch(value) and not CREDENTIAL.match(value) and len(value) <= 100:
        return value
    return "withheld: not a recognizable model name"


def number(value: object) -> object:
    """Numeric settings only; other literals are not copied out of the source."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "non-numeric or unresolved value"
    return value


def python_observations(tree: ast.AST, file: str) -> tuple[dict, set[int]]:
    """Structured declarations from one parsed module and lines to drop from text hits."""
    found: dict[str, list[dict]] = {name: [] for name in RULES}
    upstream_lines: set[int] = set()

    def add(test: str, line: int, kind: str, value: object = None) -> None:
        if len(found[test]) < MAX_ITEMS:
            item = {"file": file, "line": line, "kind": kind}
            if value is not None:
                item["value"] = value
            found[test].append(item)

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            names = [dotted(t) for t in getattr(node.type, "elts", [node.type])]
            if any(UPSTREAM_ERROR.search(name) for name in names):
                upstream_lines.add(node.lineno)
                add("endpoint_controls", node.lineno, "upstream_rate_limit_handler")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                name = dotted(decorator)
                if re.search(r"(?:^|\.)limit(?:er)?$", name) or "ratelimit" in name.lower():
                    add("endpoint_controls", decorator.lineno, "inbound_rate_limit_decorator")
        elif isinstance(node, ast.Call):
            name = dotted(node)
            if name.split(".")[-1] == "Depends" and node.args:
                dependency = dotted(node.args[0])
                if INBOUND.search(dependency):
                    add("endpoint_controls", node.lineno, "request_dependency", dependency)
            if name.endswith("add_middleware") and node.args:
                middleware = dotted(node.args[0])
                if re.search(r"limit|auth|session", middleware, re.I):
                    add("endpoint_controls", node.lineno, "middleware", middleware)
            for keyword in node.keywords:
                if keyword.arg in ("timeout", "max_retries", "retries", "read_timeout"):
                    value = literal(keyword.value)
                    add("timeouts_retries", node.lineno, keyword.arg, number(value))
                if keyword.arg in ("model", "model_name"):
                    value = literal(keyword.value)
                    if isinstance(value, str):
                        add("model_config", node.lineno, "model_argument", model_name(value))
                if keyword.arg in ("ttl", "ttl_seconds", "expire", "ex", "max_age"):
                    value = literal(keyword.value)
                    add("retention", node.lineno, f"expiry_argument:{keyword.arg}", number(value))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = dotted(target)
                if not name:
                    continue
                lower = name.lower()
                value = literal(node.value)
                if (lower == "model" or lower.endswith(("_model", ".model"))) and isinstance(
                    value, str
                ):
                    add("model_config", node.lineno, "model_assignment", model_name(value))
                elif SESSION_STORE.search(lower) and isinstance(node.value, ast.Dict | ast.Call):
                    if isinstance(node.value, ast.Dict) or dotted(node.value) in (
                        "dict",
                        "defaultdict",
                        "collections.defaultdict",
                        "OrderedDict",
                    ):
                        add("retention", node.lineno, "in_memory_store_without_declared_ttl", name)
    return found, upstream_lines


def scan(root: Path = Path("/source")) -> dict:
    hits = {name: [] for name in RULES}
    observations = {name: [] for name in RULES}
    files = parsed = 0
    parse_errors = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in EXTENSIONS and path.name not in ("Dockerfile", ".env"):
            continue
        files += 1
        relative = path.relative_to(root).as_posix()
        text = path.read_text(errors="replace")
        skip: set[int] = set()
        if path.suffix == ".py" and len(text) <= MAX_PYTHON_BYTES:
            try:
                found, skip = python_observations(ast.parse(text, filename=relative), relative)
                parsed += 1
                for name, items in found.items():
                    observations[name].extend(items[: MAX_ITEMS - len(observations[name])])
            except (SyntaxError, ValueError, RecursionError):
                if len(parse_errors) < MAX_ITEMS:
                    parse_errors.append(relative)
        for line, content in enumerate(text.splitlines(), 1):
            if content.lstrip().startswith(("#", "//")):
                continue
            for name, (category, pattern, message) in RULES.items():
                if name == "guardrail_path" and re.match(r"\s*(?:async\s+)?def\b", content):
                    continue
                if name == "ci_safety" and "/.github/workflows/" not in "/" + relative:
                    continue
                if name == "endpoint_controls" and (line in skip or UPSTREAM_ERROR.search(content)):
                    continue
                if re.search(pattern, content, re.I) and len(hits[name]) < MAX_ITEMS:
                    # Return location ONLY. Host masks the source excerpt before persistence.
                    hits[name].append(
                        {"file": relative, "line": line, "category": category, "message": message}
                    )
    for item in observations["endpoint_controls"]:
        # Structured inbound declarations count as declarations; upstream handlers never do.
        if item["kind"] != "upstream_rate_limit_handler" and len(hits["endpoint_controls"]) < 10:
            if not any(
                h["file"] == item["file"] and h["line"] == item["line"]
                for h in hits["endpoint_controls"]
            ):
                hits["endpoint_controls"].append(
                    {
                        "file": item["file"],
                        "line": item["line"],
                        "category": "configuration_reliability",
                        "message": RULES["endpoint_controls"][2],
                    }
                )
    return {
        "version": "controls-v2",
        "files": files,
        "python_files_parsed": parsed,
        "python_parse_errors": parse_errors,
        "hits": hits,
        "observations": observations,
    }


if __name__ == "__main__":
    print(json.dumps(scan(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/source"))))
