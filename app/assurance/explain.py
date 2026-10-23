"""Optional AI explanation of saved White-box findings.

The explanation is supplemental: it never changes a verdict, score, severity or review
state. Every attempt goes through the shared metering/retry path and is recorded,
including parse failures and unknown billing. Source excerpts go to a cloud judge only
with explicit consent for that request; the default is local judges only.
"""

import asyncio
import hashlib
import json
import time

from pydantic import SecretStr

from ..blackbox import metering
from ..blackbox.judge import judge_request
from ..blackbox.judge_credentials import key_for_judge
from ..blackbox.judge_recovery import local_fallbacks
from ..blackbox.quota import ProviderQuotaUnavailable
from ..blackbox.scheduling import Halted, Runtime
from ..blackbox.schema import JudgeSelection, Settings
from ..blackbox.studio_engine import judge_config
from .privacy import safe
from .readiness import evidence_status

ASSESSMENTS = {
    "confirmed_issue",
    "likely_false_positive",
    "needs_verification",
    "limited_pass",
    "declaration_only",
    "not_verified",
}
LIMITS = {
    "checks": 20,
    "excerpts_per_check": 3,
    "excerpt_chars": 500,
    "max_output_tokens": 2500,
    "judges": 3,
    "raw_chars": 2000,
}
INSTRUCTIONS = (
    "You explain saved source-scan results for a non-technical reader. Use ONLY the supplied "
    "records. Do not change or second-guess how a check was scored; explain it. For every "
    "check, return exactly one entry with the same test_id. assessment must be one of: "
    + ", ".join(sorted(ASSESSMENTS))
    + ". quotes must be exact substrings copied from that check's reason or excerpts. Reply "
    'with JSON only: {"summary": str, "checks": [{"test_id": str, "assessment": str, '
    '"explanation": str, "fix": str, "quotes": [str]}]}'
)


def payload(run: dict) -> list[dict]:
    """Bounded, already-masked White records; re-masked before leaving the process."""
    status = {row["key"]: row for row in evidence_status(run)["checks"]}
    rows = []
    for finding in run.get("findings", []):
        if finding["mode"] != "white" or len(rows) >= LIMITS["checks"]:
            continue
        guide = status.get(f"{finding['bot']}:white:{finding['test_id']}", {})
        rows.append(
            safe(
                {
                    "test_id": finding["test_id"],
                    "bot": finding["bot"],
                    "verdict": finding["verdict"],
                    "result_type": guide.get("outcome_label", ""),
                    "reason": finding["explanation"][: LIMITS["excerpt_chars"]],
                    "excerpts": [
                        f"{e.get('file', '')}:{e.get('line') or ''} "
                        + e["excerpt"][: LIMITS["excerpt_chars"]]
                        for e in finding.get("evidence", [])[: LIMITS["excerpts_per_check"]]
                    ],
                }
            )
        )
    return rows


def validate(content: str, records: list[dict]) -> dict:
    """Strict schema, exact check IDs and grounded quotes; anything else is rejected."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ValueError("Output is not an object with a checks list.")
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("Output has no summary.")
    expected = [(r["bot"], r["test_id"]) for r in records]
    by_id = {r["test_id"]: r for r in records}
    returned = [item.get("test_id") if isinstance(item, dict) else None for item in data["checks"]]
    if sorted(returned, key=str) != sorted((t for _, t in expected), key=str):
        missing = sorted(set(by_id) - set(filter(None, returned)))
        extra = sorted(set(filter(None, returned)) - set(by_id), key=str)
        raise ValueError(
            "Check IDs do not match exactly"
            + (f"; missing {', '.join(missing[:5])}" if missing else "")
            + (f"; unexpected {', '.join(map(str, extra[:5]))}" if extra else "")
            + "."
        )
    checks = []
    for item in data["checks"]:
        record = by_id[item["test_id"]]
        if item.get("assessment") not in ASSESSMENTS:
            raise ValueError(f"Invalid assessment for {item['test_id']}.")
        if not all(
            isinstance(item.get(k), str) and item[k].strip() for k in ("explanation", "fix")
        ):
            raise ValueError(f"Missing explanation or fix for {item['test_id']}.")
        quotes = item.get("quotes")
        grounding = " ".join([record["reason"], *record["excerpts"]])
        if (
            not isinstance(quotes, list)
            or not quotes
            or not all(isinstance(q, str) and q.strip() and q.strip() in grounding for q in quotes)
        ):
            raise ValueError(f"Quotes for {item['test_id']} are not exact supplied text.")
        checks.append(
            {
                "test_id": item["test_id"],
                "bot": record["bot"],
                "assessment": item["assessment"],
                "explanation": str(safe(item["explanation"]))[:2000],
                "fix": str(safe(item["fix"]))[:1000],
                "quotes": [str(safe(q))[:500] for q in quotes[:5]],
                "recorded_verdict": record["verdict"],
            }
        )
    return {"summary": str(safe(data["summary"]))[:2000], "checks": checks}


async def candidates(config: Settings, cloud_consent: bool) -> list[JudgeSelection]:
    """Requested judges, filtered to local ones unless cloud use was consented."""
    chosen = [j for j in config.judges if cloud_consent or j.local]
    if not chosen:
        chosen = await local_fallbacks(config)
    return chosen[: LIMITS["judges"]]


async def explain(run: dict, config: Settings, cloud_consent: bool) -> dict:
    """Try permitted judges in order; return an accepted explanation or a recorded failure."""
    records = payload(run)
    attempts = []
    result = {
        "id": hashlib.sha256(f"{run['id']}:{time.time()}".encode()).hexdigest()[:16],
        "created_at": time.time(),
        "source": "Automated AI explanation",
        "purpose": "Supplemental explanation. Original verdicts, severity and reviews are unchanged.",
        "cloud_consent": cloud_consent,
        "payload_hash": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
        "checks_sent": len(records),
        "status": "failed",
        "attempts": attempts,
    }
    if not records:
        result["reason"] = "This test has no White-box findings to explain."
        return result
    judges = await candidates(config, cloud_consent)
    if not judges:
        result["reason"] = (
            "No permitted judge is available. Start a local model in Ollama, or allow a cloud "
            "judge for this explanation."
        )
        return result
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps({"checks": records}, ensure_ascii=False)},
    ]
    for entry in judges:
        selected = judge_config(config, entry)
        if not selected.judge_token and not entry.local:
            key = key_for_judge(entry.url)
            selected.judge_token = SecretStr(key) if key else None
        body = {
            "model": entry.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": LIMITS["max_output_tokens"],
            "response_format": {"type": "json_object"},
        }

        async def send(body=body, selected=selected):
            return await metering.completion(
                selected.judge_url,
                body,
                selected.judge_token.get_secret_value() if selected.judge_token else "",
                selected.timeout,
            )

        attempt = {"model": entry.model, "local": entry.local, "started_at": time.time()}
        attempts.append(attempt)
        content = ""
        runtime = Runtime(selected, asyncio.Event())
        try:
            # Shared provider limits/pacing and metering; no separate pool or SDK retries.
            with (
                runtime.context(),
                metering.scope(
                    run["id"],
                    "white",
                    selected,
                    category="code_security",
                    test_case_id="white-ai-explanation",
                ),
            ):
                data = await judge_request(selected, send, messages, LIMITS["max_output_tokens"])
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
            attempt["provider_model"] = str(data.get("model") or "Not supplied")
            attempt["output_hash"] = hashlib.sha256(content.encode()).hexdigest()
            if choice.get("finish_reason") not in (None, "stop"):
                raise ValueError(f"Output incomplete ({choice.get('finish_reason')}).")
            accepted = validate(content, records)
        except (metering.BudgetLimit, Halted) as exc:
            attempt.update(status="stopped", reason=type(exc).__name__)
            if isinstance(exc, ProviderQuotaUnavailable):
                attempt["reason"] = "Provider quota or billing unavailable."
                continue
            break
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            attempt.update(status="rejected", reason=str(safe(str(exc)))[:500])
            if content:
                attempt["raw_excerpt"] = str(safe(content))[: LIMITS["raw_chars"]]
            continue
        except Exception as exc:  # Provider/network failure: record and try the next judge.
            from ..blackbox.connectors import safe_error

            attempt.update(status="failed", reason=safe_error(exc) or type(exc).__name__)
            continue
        finally:
            await runtime.close()
        attempt["status"] = "accepted"
        result.update(
            status="accepted",
            model=entry.model,
            provider_model=attempt["provider_model"],
            local=entry.local,
            **accepted,
        )
        return result
    result["reason"] = (
        "No judge returned a valid, grounded explanation. No explanation was accepted."
    )
    return result
