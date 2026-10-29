"""Classify why a provider call failed, so an account problem is never read as a bot defect.

In the saved VoltKart retest four different conditions all surfaced as "the judge was
unavailable": OpenAI listed its models but refused inference because the API billing quota was
exhausted; Gemini 2.5 Flash Lite appeared in discovery but its inference call reported the model
unavailable for new users; VoltKart's own Gemini calls hit HTTP 429; and some responses were
simply not valid verdicts. They need different actions - add credit, fix a key, wait and retry,
pick another model, inspect the output - so they are reported as different states.

Nothing here retries by itself. It names a condition and states whether waiting could help; the
existing scheduler and `judge_request` own the bounded retries and the pacing.
"""

import re

#: Discovery and inference are separate capabilities. An account can list a model it is not
#: entitled to call, so a successful listing is never evidence that judging will work.
DISCOVERY_NOTE = (
    "A model listing shows what the account can enumerate, not what it can call. Inference "
    "readiness is only established by a successful metered request that returns a valid verdict."
)

#: Each state carries the owner action it implies and whether waiting alone could resolve it.
STATES = {
    "billing_exhausted": {
        "label": "Billing or credit exhausted",
        "retryable": False,
        "action": "Add provider credit or configure a funded provider, then resume pending cases.",
    },
    "quota_exhausted": {
        "label": "Daily quota exhausted",
        "retryable": False,
        "action": "Wait for the provider's quota reset or raise the plan limit, then resume. A "
        "new key on the same project usually shares the same quota.",
    },
    "authentication_failed": {
        "label": "Authentication rejected",
        "retryable": False,
        "action": "Check the API key for this endpoint and its permissions, then re-enter it.",
    },
    "model_unavailable": {
        "label": "Model not available to this account",
        "retryable": False,
        "action": "The model was listed but cannot be called by this account. Choose a model the "
        "account is entitled to use, or request access.",
    },
    "rate_limited": {
        "label": "Rate limited",
        "retryable": True,
        "action": "Transient. Studio honours the provider's retry guidance within its bounded "
        "retry budget; no change is needed unless it persists.",
    },
    "invalid_verdict": {
        "label": "Response was not a usable verdict",
        "retryable": True,
        "action": "The provider replied but the output was unusable. Inspect the retained raw "
        "output; a different judge model may be more reliable for this rubric.",
    },
    "transport_error": {
        "label": "Could not reach the provider",
        "retryable": True,
        "action": "Check connectivity to the endpoint, then retry.",
    },
    "unclassified": {
        "label": "Unclassified provider failure",
        "retryable": False,
        "action": "Read the recorded reason. Studio did not recognise this condition, so it is "
        "not assumed to be transient.",
    },
}

_BILLING = (
    "insufficient balance",
    "insufficient_quota",
    "billing_hard_limit",
    "exceeded_current_quota_error",
    "billing quota is exhausted",
    "billing quota",
    "add credit",
)
_DAILY = (
    "generaterequestsperday",
    "requestsperdayperproject",
    "tokensperday",
    "daily quota",
    "daily api quota",
    "quota_exhausted",
)
_AUTH = (
    "api key not valid",
    "invalid api key",
    "incorrect api key",
    "unauthenticated",
    "permission_denied",
    "missing credentials",
    "invalid_api_key",
)
#: Phrases a provider uses when a listed model cannot actually be called. "not found" alone is
#: ambiguous, so a model name or an explicit entitlement phrase is required.
_MODEL = (
    "model not found",
    "does not exist or you do not have access",
    "not available for new users",
    "model is not available",
    "unsupported model",
    "model_not_found",
    "not supported for this model",
    "does not have access to model",
)
_VERDICT = (
    "judge must return",
    "judge omitted",
    "judge score must be",
    "invalid pairwise judgment",
    "judge response was incomplete",
    "judge evidence did not match",
    "judge chose an invalid evidence id",
    "batch ids missing",
)


def _text(error) -> str:
    parts = [str(error), str(getattr(error, "body", ""))]
    response = getattr(error, "response", None)
    if response is not None:
        try:
            parts.append(str(response.json()))
        except (ValueError, AttributeError, RuntimeError):
            parts.append(str(getattr(response, "text", "")))
    return " ".join(parts).casefold()


def status_code(error):
    """The HTTP status a provider returned, when the exception carries one."""
    response = getattr(error, "response", None)
    return getattr(error, "status_code", None) or getattr(response, "status_code", None)


def classify(error) -> str:
    """Name the condition behind a provider failure. Never raises on an unfamiliar error."""
    text = _text(error)
    code = status_code(error)
    if any(marker in text for marker in _BILLING):
        return "billing_exhausted"
    if any(marker in text for marker in _DAILY):
        return "quota_exhausted"
    if any(marker in text for marker in _VERDICT):
        return "invalid_verdict"
    if code in (401, 403) or any(marker in text for marker in _AUTH):
        return "authentication_failed"
    if any(marker in text for marker in _MODEL):
        return "model_unavailable"
    if code == 429:
        return "rate_limited"
    if code in (408, 500, 502, 503, 504):
        return "transport_error"
    if re.search(r"\b(timed out|timeout|connect(ion)? (failed|error|refused))\b", text):
        return "transport_error"
    return "unclassified"


def describe(error) -> dict:
    """Classification plus the owner action it implies, for display beside a result."""
    state = classify(error)
    row = STATES[state]
    return {
        "state": state,
        "label": row["label"],
        "retryable": row["retryable"],
        "action": row["action"],
        "http_status": status_code(error),
    }


def needs_owner_action(error) -> bool:
    """True when no amount of waiting or retrying can resolve the condition."""
    return not STATES[classify(error)]["retryable"]


# --- panel and fallback policy ------------------------------------------------------------------

#: Stated on every Run so a reader knows what the panel was allowed to do, rather than inferring
#: it from which judges happen to appear in the results.
PANEL_POLICY = {
    "version": "judge-panel-policy-v1",
    "rules": [
        "Every requested judge is attempted. A requested judge is never removed to make the "
        "panel look complete.",
        "A judge that fails may be replaced only by an explicitly selected local fallback, or by "
        "an installed local model when automatic local fallback is enabled. No model is "
        "downloaded, and no cloud judge is substituted for a local one.",
        "The target chatbot's model is never changed because its Judge failed.",
        "If a requested judge produces no valid verdict, the Case keeps the verdicts it has, is "
        "marked as an incomplete panel and reports Not tested with the partial estimate "
        "retained for review.",
        "Every requested model, the model that actually scored the Case, each failure reason and "
        "each switch are recorded per verdict.",
        "A mixed panel is reported as mixed. Judges are not interchangeable, and a panel without "
        "human calibration is not a validated measurement.",
    ],
    "discovery_note": DISCOVERY_NOTE,
}


def panel_policy(config) -> dict:
    """The policy in force for this Run, with the judges it was configured to use."""
    requested = [j for j in getattr(config, "judges", []) if not j.fallback]
    declared = [j for j in getattr(config, "judges", []) if j.fallback]
    return {
        **PANEL_POLICY,
        "requested_judges": [
            {"model": j.model, "local": bool(j.local), "endpoint": j.url} for j in requested
        ],
        "declared_fallbacks": [{"model": j.model, "local": bool(j.local)} for j in declared],
        "automatic_local_fallback": bool(getattr(config, "auto_local_fallback", False)),
    }
