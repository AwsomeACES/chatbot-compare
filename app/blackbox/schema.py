"""Validate public evaluation settings, target interfaces and imported case sets."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, PrivateAttr, SecretStr, model_validator

CATEGORIES = {
    "hallucination": "Hallucination testing (answer accuracy)",
    "bias": "Bias testing (fairness)",
    "injection": "Prompt injection",
    "jailbreak": "Multi-turn jailbreak",
    "guardrails": "Guardrails testing (safety policy)",
    "prompt_leakage": "System prompt leakage",
    "pii": "Personal data leakage",
    "toxicity": "Toxicity",
    "over_refusal": "Unnecessary refusals",
    "consistency": "Consistency",
    "calibration": "Acknowledging uncertainty",
    "scope": "Scope adherence",
    "memory": "Conversation memory",
    "language": "Language and tone",
    "performance": "Performance testing (speed and reliability)",
    "functional": "Functional correctness",
}

# Preserve the original default suite for legacy callers.
LEGACY_CATEGORIES = tuple(CATEGORIES)
CATEGORIES.update(
    {
        "hallucination_relevant": "Relevant answer + hallucination",
        "hallucination_irrelevant": "Irrelevant request + hallucination",
        "bias_religion": "Bias: religion",
        "bias_caste": "Bias: caste",
        "bias_sex": "Bias: sex / gender",
        "bias_colour": "Bias: skin colour",
    }
)

CATEGORY_DETAILS = {
    "hallucination": {
        "description": "Check reference facts when supplied; otherwise probe invented identifiers and unsupported claims.",
        "requires": "Running chatbot and AI judge. Reference facts are optional; required for catalogue accuracy.",
    },
    "bias": {
        "description": (
            "Compare matched scenarios across names, age, religion, caste, region, "
            "disability, income, language, orientation and other "
            "attributes."
        ),
        "requires": "Running chatbot and AI judge. Paired starter prompts are included.",
    },
    "guardrails": {
        "description": "Check whether the chatbot follows your safety rules and authorization limits.",
        "requires": "Running chatbot, your safety policy, and a configured AI judge.",
    },
    "performance": {
        "description": "Measure response time, request failures and timeouts using sequential requests.",
        "requires": "Running chatbot and speed-test consent. No AI judge is needed.",
    },
}


class Target(BaseModel):
    name: str = Field(default="My chatbot", min_length=1, max_length=100)
    url: str = Field(default="", max_length=2048)
    kind: Literal["auto", "rest", "openai", "web", "zip"] = "auto"
    archive_id: str = ""
    request_defaults: dict = Field(default_factory=dict)
    message_field: str = "message"
    response_field: str = ""
    session_field: str = "conversation_id"
    history_field: str = ""
    model: str = ""
    model_alias: str = Field(default="", max_length=250)
    local_model: bool = False
    token: SecretStr | None = None
    input_selector: str = ""
    answer_selector: str = ""
    send_selector: str = ""

    @model_validator(mode="after")
    def validate_url(self):
        if len(str(self.request_defaults)) > 10000:
            raise ValueError("Request defaults exceed 10 KB.")
        if self.kind != "zip":
            p = urlsplit(self.url)
            if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
                raise ValueError(
                    "Enter a complete HTTP(S) chat or API URL without credentials in the URL."
                )
        return self


class ExactChecks(BaseModel):
    model_config = {"extra": "forbid"}
    required: list[str] = Field(default_factory=list, max_length=100)
    forbidden: list[str] = Field(default_factory=list, max_length=100)
    canary: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_terms(self):
        if any(not t.strip() or len(t) > 1000 for t in self.required + self.forbidden):
            raise ValueError("Check strings must contain 1–1000 characters.")
        if self.canary and not self.canary.strip():
            raise ValueError("Canary must not be blank.")
        return self


class ImportedCase(BaseModel):
    model_config = {"extra": "forbid"}
    category: str
    bias_subtype: str = ""
    derived: bool = False
    name: str = Field(min_length=1, max_length=200)
    turns: list[str] = Field(min_length=1, max_length=8)
    expected: str = Field(min_length=1, max_length=12000)
    parallel: bool = False
    reference: dict | str | None = None
    checks: ExactChecks = Field(default_factory=ExactChecks)

    @model_validator(mode="before")
    @classmethod
    def accept_prompt_rubric(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "prompt" in value and "turns" not in value:
                value["turns"] = [value.pop("prompt")]
            if "rubric" in value and "expected" not in value:
                value["expected"] = value.pop("rubric")
        return value

    @model_validator(mode="after")
    def validate_case(self):
        if self.category not in CATEGORIES:
            raise ValueError("Unknown case category.")
        if not self.name.strip() or not self.expected.strip():
            raise ValueError("Case name and expected behavior cannot be blank.")
        if any(not t.strip() or len(t) > 12000 for t in self.turns):
            raise ValueError("Each turn must contain 1–12000 characters.")
        if self.parallel and len(self.turns) < 2:
            raise ValueError("Paired cases require at least two prompts.")
        if isinstance(self.reference, dict) and self.reference.get("checks"):
            ExactChecks.model_validate(self.reference["checks"])
        return self


class JudgeSelection(BaseModel):
    model: str = Field(min_length=1, max_length=250)
    url: str = "http://127.0.0.1:11434/v1/chat/completions"
    token: SecretStr | None = None
    local: bool = False
    fallback: bool = False
    price_alias: str = ""

    @model_validator(mode="after")
    def valid_endpoint(self):
        p = urlsplit(self.url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
            raise ValueError("Judge URL must be HTTP(S) without embedded credentials.")
        if self.local and p.hostname not in (
            "127.0.0.1",
            "localhost",
            "::1",
            "host.docker.internal",
        ):
            raise ValueError("Local judges must use a local host.")
        if self.fallback and not self.local:
            raise ValueError("Automatic fallback must be an explicitly selected local judge.")
        return self


class Settings(BaseModel):
    ownership_confirmed: bool = False
    auto_local_fallback: bool = True
    local_judge_timeout: float = Field(default=240, ge=20, le=600)
    _fallback_checked: bool = PrivateAttr(default=False)
    _fallback_lock: object = PrivateAttr(default=None)
    _discovered_fallbacks: list = PrivateAttr(default_factory=list)
    _judge_health: dict = PrivateAttr(default_factory=dict)
    simple_mode: bool = False
    # "" keeps the protocol's default screening suite; a declared name selects that suite.
    scenario_suite: str = Field(default="", max_length=60)
    retention_days: int = Field(default=0, ge=0, le=3650)
    judge_batch_size: int = Field(default=1, ge=1, le=8)
    judge_batch_wait_ms: int = Field(default=40, ge=0, le=200)
    local_classifiers: dict = Field(default_factory=dict)
    provider_limits: dict[str, int] = Field(default_factory=dict)
    _protocol_override: dict | None = PrivateAttr(default=None)
    _reproduced_from: str = PrivateAttr(default="")
    judges: list[JudgeSelection] = Field(default_factory=list, max_length=8)
    repeat_counts: dict[str, int] = Field(default_factory=dict)
    category_weights: dict[str, float] = Field(default_factory=dict)

    _setup_notes: list[str] = PrivateAttr(default_factory=list)
    _used_secrets: list[str] = PrivateAttr(default_factory=list)
    targets: list[Target] = Field(min_length=1, max_length=4)
    categories: list[str] = Field(default_factory=lambda: list(LEGACY_CATEGORIES))
    cases_per_category: int = Field(default=30, ge=1, le=100)
    custom_cases: list[ImportedCase] = Field(default_factory=list, max_length=2000)
    include_template_variations: bool = False
    all_imported_cases: bool = False
    references: list[dict] = Field(default_factory=list, max_length=2000)
    policy: str = Field(default="", max_length=20000)
    scope: str = Field(default="", max_length=10000)
    judge_url: str = "http://127.0.0.1:1234/v1/chat/completions"
    judge_model: str = ""
    judge_token: SecretStr | None = None
    collect_only: bool = False
    judge_enabled: bool = True
    primary_judge_family: str = Field(default="", max_length=100)
    secondary_judge_enabled: bool = False
    secondary_judge_url: str = "http://127.0.0.1:1234/v1/chat/completions"
    secondary_judge_model: str = Field(default="", max_length=250)
    secondary_judge_family: str = Field(default="", max_length=100)
    secondary_judge_token: SecretStr | None = None
    secondary_judge_consent: bool = False
    secondary_sample_rate: float = Field(default=0.2, gt=0, le=1)
    secondary_judge_alias: str = Field(default="", max_length=250)
    secondary_judge_local: bool = False
    regression_threshold: float = Field(default=5, ge=0, le=100)
    consent: bool = False
    judge_consent: bool = False
    performance_consent: bool = False
    case_concurrency: int = Field(default=4, ge=1, le=16)
    target_concurrency: int = Field(default=4, ge=1, le=8)
    judge_concurrency: int = Field(default=4, ge=1, le=8)
    judge_pause_seconds: float = Field(default=0.25, ge=0.25, le=60)
    request_pause_seconds: float = Field(default=0.25, ge=0.25, le=60)
    timeout: float = Field(default=20, ge=1, le=120)
    max_minutes: int = Field(default=20, ge=1, le=720)
    latency_budget_seconds: float = Field(default=5, ge=0.1, le=60)
    seed: int = 42
    min_coverage: float = Field(default=0.8, gt=0, le=1)
    judge_model_alias: str = Field(default="", max_length=250)
    judge_local_model: bool = False
    max_budget_usd: str | None = None
    price_snapshot_id: str = ""
    cost_settings_snapshot: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check(self):
        if self.collect_only and (self.judge_enabled or self.simple_mode):
            raise ValueError(
                "Transcript-only collection requires judge disabled and legacy case planning."
            )
        if any(type(n) is not int or not 1 <= n <= 20 for n in self.repeat_counts.values()):
            raise ValueError("Repeat counts must be integers between 1 and 20.")
        if any(type(n) is not int or not 1 <= n <= 16 for n in self.provider_limits.values()):
            raise ValueError("Provider concurrency limits must be integers from 1 to 16.")
        import math

        if any(not math.isfinite(n) or n <= 0 for n in self.category_weights.values()):
            raise ValueError("Weights must be finite and positive.")

        if self.secondary_judge_enabled:
            if not self.judge_enabled:
                raise ValueError("Second-judge agreement requires the primary judge enabled.")
            if not self.secondary_judge_model.strip():
                raise ValueError("Enter a second judge model.")
            if (
                not self.primary_judge_family.strip()
                or not self.secondary_judge_family.strip()
                or self.primary_judge_family.strip().casefold()
                == self.secondary_judge_family.strip().casefold()
            ):
                raise ValueError(
                    "Declare different primary and secondary model families for agreement checks."
                )
            if self.secondary_judge_model.casefold() == self.judge_model.casefold():
                raise ValueError("Use a different secondary judge model.")
            parsed = urlsplit(self.secondary_judge_url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "Enter a valid second-judge HTTP(S) URL without embedded credentials."
                )
        if self.max_budget_usd is not None:
            from .pricing import decimal

            self.max_budget_usd = str(decimal(self.max_budget_usd))
        self.categories = list(dict.fromkeys(self.categories))
        if not self.categories or any(c not in CATEGORIES for c in self.categories):
            raise ValueError("Choose supported black-box categories.")
        if len(str(self.references)) > 300000:
            raise ValueError("References exceed 300 KB.")
        for ref in self.references:
            if ref.get("checks"):
                ExactChecks.model_validate(ref["checks"])
        if len(str([c.model_dump() for c in self.custom_cases])) > 500000:
            raise ValueError("Case set exceeds 500 KB.")
        identities = [(c.category, c.name.casefold().strip()) for c in self.custom_cases]
        if len(identities) != len(set(identities)):
            raise ValueError("Case names must be unique within a category.")
        return self
