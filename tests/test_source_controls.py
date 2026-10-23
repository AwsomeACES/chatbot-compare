"""Trusted control worker: syntax-only parsing, declarations never become passes."""

import importlib.util
from pathlib import Path

from app.assurance.white import parse

WORKER = Path(__file__).parents[1] / "app/assurance/rules/control_worker.py"
spec = importlib.util.spec_from_file_location("control_worker", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def scan(root: Path, files: dict[str, str]) -> dict:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return worker.scan(root)


def output(data: dict) -> dict:
    return {"data": data, "version": data["version"], "image_id": "sha256:x", "ruleset": "v1"}


def test_upstream_rate_limit_handler_is_not_inbound_access_control(tmp_path):
    data = scan(
        tmp_path,
        {
            "providers.py": (
                "import openai\n"
                "def ask():\n"
                "    try:\n"
                "        return call()\n"
                "    except openai.RateLimitError:\n"
                "        return 'busy'\n"
            )
        },
    )
    assert data["hits"]["endpoint_controls"] == []
    kinds = [o["kind"] for o in data["observations"]["endpoint_controls"]]
    assert kinds == ["upstream_rate_limit_handler"]
    finding = parse("endpoint_controls", output(data), tmp_path, 0)
    assert finding.verdict == "not_tested" and finding.score is None
    assert "do not limit or authenticate incoming requests" in finding.explanation
    assert finding.details["outcome"] == "insufficient_evidence"


def test_inbound_declarations_are_declarations_not_passes(tmp_path):
    data = scan(
        tmp_path,
        {
            "app.py": (
                "from fastapi import Depends\n"
                "@limiter.limit('5/minute')\n"
                "def chat(user=Depends(get_current_user)):\n"
                "    return 1\n"
            )
        },
    )
    kinds = {o["kind"] for o in data["observations"]["endpoint_controls"]}
    assert {"inbound_rate_limit_decorator", "request_dependency"} <= kinds
    finding = parse("endpoint_controls", output(data), tmp_path, 0)
    assert finding.verdict == "exists" and finding.control is True
    assert finding.score is None and finding.confidence == "Low"


def test_model_timeout_and_session_observations_withhold_unsafe_literals(tmp_path):
    secret = "sk-" + "syntheticOnly" * 3
    data = scan(
        tmp_path,
        {
            "config.py": (
                "api_model = 'gemini-2.5-flash'\n"
                f"backup_model = '{secret}'\n"
                "sessions = {}\n"
                "client = Client(timeout=30, max_retries='many')\n"
            )
        },
    )
    models = [o["value"] for o in data["observations"]["model_config"]]
    assert "gemini-2.5-flash" in models
    assert secret not in str(data)
    timeouts = {o["kind"]: o["value"] for o in data["observations"]["timeouts_retries"]}
    assert timeouts == {"timeout": 30, "max_retries": "non-numeric or unresolved value"}
    retention = parse("retention", output(data), tmp_path, 0)
    assert retention.verdict == "not_tested"
    assert "in memory store without declared ttl" in retention.explanation
    assert retention.details["source_observations"][0]["value"] == "sessions"
    model = parse("model_config", output(data), tmp_path, 0)
    assert model.verdict == "not_tested" and "gemini-2.5-flash" in model.explanation


def test_parse_errors_and_nested_workflows_do_not_execute_source(tmp_path):
    marker = tmp_path / "executed.txt"
    data = scan(
        tmp_path,
        {
            "repo-main/bot.py": f"open({str(marker)!r}, 'w').write('ran')\n",
            "repo-main/broken.py": "def (:\n",
            "repo-main/.github/workflows/ci.yml": "run: pytest tests/safety_guardrail_test.py\n",
        },
    )
    assert not marker.exists()
    assert data["python_parse_errors"] == ["repo-main/broken.py"]
    assert data["python_files_parsed"] == 1
    assert data["hits"]["ci_safety"][0]["file"] == "repo-main/.github/workflows/ci.yml"
