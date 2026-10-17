"""Bind model-selected evidence IDs to literal recorded output excerpts."""


def options(outputs: list[str]) -> list[str]:
    """Keep choices short and distributed across turns, including later corrections."""
    rows = []
    for output in outputs:
        chunks = [line.strip() for line in output.splitlines() if len(line.strip()) >= 8]
        if not chunks:
            chunks = [output.strip()]
        for text in (chunks[0], chunks[-1]):
            quote = text[:500]
            if quote and quote not in rows:
                rows.append(quote)
    return rows[:16]


def bind(result: dict, choices: list[str]) -> dict:
    """Indices never create evidence: reject IDs outside the exact offered list."""
    if "evidence_ids" not in result:
        return result
    ids = result["evidence_ids"]
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 8
        or any(type(i) is not int or not 0 <= i < len(choices) for i in ids)
    ):
        raise ValueError("Judge chose an invalid evidence ID.")
    existing = result.get("evidence", [])
    if not isinstance(existing, list):
        raise ValueError("Judge evidence must be a list.")
    return {
        **result,
        "evidence": existing + [choices[i] for i in ids],
        "evidence_source": "recorded-excerpt-ids",
    }
