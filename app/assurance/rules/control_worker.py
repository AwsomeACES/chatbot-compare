"""Trusted text scanner run ONLY inside the read-only, networkless container.

No uploaded modules/config are imported or executed. Positive matches establish
textual control declarations, never their effectiveness or complete dataflow.
"""

import json
import re
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


def scan():
    hits = {name: [] for name in RULES}
    files = 0
    for path in Path("/source").rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in EXTENSIONS and path.name not in ("Dockerfile", ".env"):
            continue
        files += 1
        for line, text in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if text.lstrip().startswith(("#", "//")):
                continue
            for name, (category, pattern, message) in RULES.items():
                if name == "guardrail_path" and re.match(r"\s*(?:async\s+)?def\b", text):
                    continue
                if name == "ci_safety" and "/.github/workflows/" not in str(path):
                    continue
                if re.search(pattern, text, re.I) and len(hits[name]) < 10:
                    # Return location ONLY. Host masks the source excerpt before persistence.
                    hits[name].append(
                        {
                            "file": str(path.relative_to("/source")),
                            "line": line,
                            "category": category,
                            "message": message,
                        }
                    )
    return {"version": "controls-v1", "files": files, "hits": hits}


if __name__ == "__main__":
    print(json.dumps(scan()))
