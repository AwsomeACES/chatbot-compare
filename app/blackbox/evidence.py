"""Conservative formatting normalization; no semantic or fuzzy similarity."""

import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "„": '"',
                "‘": "'",
                "’": "'",
                "–": "-",
                "—": "-",
                "−": "-",
                "…": "...",
            }
        )
    )
    return " ".join(text.casefold().split())


def pattern(text):
    return (
        (r"(?<!\w)" if text[0].isalnum() else "")
        + re.escape(text)
        + (r"(?!\w)" if text[-1].isalnum() else "")
    )


def match_quote(quote, outputs):
    q = normalize(quote)
    if not q:
        return None
    for index, output in enumerate(outputs):
        normalized = normalize(output)
        if re.search(pattern(q), normalized):
            return {"output_index": index, "method": "exact" if quote in output else "normalized"}
    # Ellipses denote a bounded omission inside a single reply, never across turns.
    parts = [p.strip() for p in q.split("...") if p.strip()]
    if (
        len(parts) < 2
        or any(sum(c.isalnum() for c in p) < 4 for p in parts)
        or sum(len(p) for p in parts) < 12
    ):
        return None
    expression = r".{0,300}?".join(pattern(p) for p in parts)
    for index, output in enumerate(outputs):
        if re.search(expression, normalize(output)):
            return {"output_index": index, "method": "ellipsis"}
    return None


def validate_evidence(evidence, outputs):
    matches = []
    unmatched = []
    if not isinstance(evidence, list) or not evidence or len(evidence) > 50:
        return [], ["Missing or invalid evidence list."]
    for quote in evidence:
        match = (
            match_quote(quote, outputs)
            if isinstance(quote, str) and 0 < len(quote) <= 12000
            else None
        )
        if match:
            matches.append({"quote": quote, **match})
        else:
            unmatched.append(quote if isinstance(quote, str) else "[Invalid quote]")
    return matches, unmatched
