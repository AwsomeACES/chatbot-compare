"""One canonical request builder for execution, audit and cache identity."""

import json

from .evidence_ids import options


def request_body(config, payload: dict, pair: bool = False) -> tuple[dict, list[str], list[str]]:
    from .judge import SYSTEM

    outputs = (
        [x["output"] for key in ("A", "B") for x in payload[key] if x.get("output")]
        if pair
        else [x["output"] for x in payload["transcript"] if x.get("output")]
    )
    choices = options(outputs)
    schema = (
        '{"winner":"A|B|tie","reason":"brief explanation","evidence_ids":[0]}'
        if pair
        else '{"score":0,"reason":"brief explanation","evidence_ids":[0]}'
    )
    body = {
        "model": config.judge_model,
        "temperature": 0,
        "max_tokens": 1500,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM
                + " Required format: "
                + schema
                + " Return literal evidence quotes or offered evidence_ids. IDs refer only to original excerpts, never translations. For paired bias, support your comparison with evidence from EACH reply.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        **payload,
                        "evidence_options": [{"id": i, "quote": q} for i, q in enumerate(choices)],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    if "gemma-4" in config.judge_model.lower():
        body["reasoning_effort"] = "minimal"
    return body, outputs, choices


# --- Evaluator identity -------------------------------------------------------------------
# Fingerprints are derived from the same builder and source that execute a request, so editing
# prompt text or evidence-validation code invalidates calibration even if nobody bumps a label.

PROMPT_TEMPLATE_VERSION = "rubric-v1"
_PROBE = {"category": "probe", "criterion": "probe", "transcript": [{"output": "probe output"}]}
_PAIR_PROBE = {
    "category": "probe",
    "criterion": "probe",
    "A": [{"output": "a"}],
    "B": [{"output": "b"}],
}


def normalize_endpoint(url: str) -> str:
    """Scheme/host/port/path identity. Credentials, query and fragment are never included."""
    from urllib.parse import urlsplit

    p = urlsplit(url or "")
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme.lower()}://{(p.hostname or '').lower()}{port}{p.path.rstrip('/')}"


def _source_hash(*objects) -> str:
    import inspect

    from .execution_cache import digest

    return digest([inspect.getsource(o) for o in objects])


def template_fingerprint(config) -> dict:
    """Prompt-template identity from the canonical builder (independent of any transcript)."""
    from .execution_cache import digest

    single, _, _ = request_body(config, _PROBE)
    pair, _, _ = request_body(config, _PAIR_PROBE, pair=True)
    return {
        "version": PROMPT_TEMPLATE_VERSION,
        "template_hash": digest(
            [
                [m["content"] for m in body["messages"] if m["role"] == "system"]
                for body in (single, pair)
            ]
            + [_source_hash(request_body)]
        ),
        "generation_hash": digest(
            {k: v for k, v in single.items() if k not in ("messages", "model")}
        ),
    }


def validation_fingerprint() -> str:
    """Hash of the code that offers, binds and validates evidence and verdicts."""
    from . import evidence, evidence_ids, judge

    return _source_hash(
        evidence_ids.options, evidence_ids.bind, evidence.validate_evidence, judge._ask_uncached
    )


def rubric_fingerprint(payload: dict) -> str:
    """Rubric/context identity: criterion, references, category, subtype, policy and scope."""
    from .execution_cache import digest

    return digest(
        {
            k: payload.get(k)
            for k in ("category", "criterion", "reference", "policy", "scope", "bias_subtype")
        }
    )


def evaluator_fingerprint(config, returned_model: str = "") -> dict:
    """Requested model + endpoint + template + validation; excludes API keys by construction."""
    from .execution_cache import digest

    t = template_fingerprint(config)
    value = {
        "schema_version": 1,
        "requested_model": config.judge_model,
        "endpoint": normalize_endpoint(config.judge_url),
        "known_model_revision": returned_model or "Not supplied by provider",
        "template_version": t["version"],
        "template_hash": t["template_hash"],
        "generation_hash": t["generation_hash"],
        "validation_hash": validation_fingerprint(),
    }
    # Provider-returned names are not immutable revisions, so they stay out of the identity hash.
    value["id"] = digest({k: v for k, v in value.items() if k != "known_model_revision"})
    return value
