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
