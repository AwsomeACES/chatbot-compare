"""Recognize account-level quota blocks without exposing upstream credentials."""

from .scheduling import Halted


class ProviderQuotaUnavailable(Halted):
    """Pause evaluation until the provider's account or daily quota is usable."""


def quota_reason(error):
    """Return a fixed public message, never raw exception bodies or request URLs."""
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    if status is not None and status != 429:
        return None
    parts = [str(error), str(getattr(error, "body", ""))]
    if response is not None:
        try:
            parts.append(str(response.json()))
        except (ValueError, AttributeError, RuntimeError):
            pass
    text = " ".join(parts).lower()
    if any(
        marker in text
        for marker in (
            "insufficient balance",
            "insufficient_quota",
            "billing_hard_limit",
            "exceeded_current_quota_error",
            "billing quota is exhausted",
        )
    ):
        return "Provider API balance or billing quota is exhausted. Add API credit or configure a funded provider, then resume pending cases."
    if any(
        marker in text
        for marker in (
            "generaterequestsperday",
            "requestsperdayperproject",
            "tokensperday",
            "daily quota",
            "daily api quota",
            "quota_exhausted",
        )
    ):
        return "Provider daily API quota is exhausted. Wait for its reset or enable a higher-quota plan, then resume pending cases. A new key on the same project may share the quota."
    return None
