"""Typed schemas for human-aligned Judge calibration (additions; no existing contract changes).

Human labels live only in these records. They are never part of a Finding, a Judge request or a
credential object, and they never change a historical score.
"""

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .schema import JudgeSelection

SCHEMA_VERSION = 1
KIND_SET = "judge_calibration_set"
KIND_EVALUATION = "judge_calibration_evaluation"
OWNER = "local owner"


class CalibrationPolicy(BaseModel):
    """Editable engineering defaults. pass_threshold is fixed at the existing 80 boundary."""

    model_config = {"extra": "ignore"}
    schema_version: int = 1
    pass_threshold: Literal[80] = 80
    min_agreement_percent: float = Field(default=80, ge=0, le=100)
    min_comparable_coverage_percent: float = Field(default=100, gt=0, le=100)
    min_distinct_scenarios: int = Field(default=10, ge=1, le=1000)
    min_human_pass_scenarios: int = Field(default=2, ge=0, le=1000)
    min_human_fail_scenarios: int = Field(default=2, ge=0, le=1000)
    max_sets: int = Field(default=50, ge=1, le=500)
    max_items_per_set: int = Field(default=200, ge=1, le=1000)
    max_sample_size: int = Field(default=100, ge=1, le=1000)
    max_rationale_chars: int = Field(default=2000, ge=100, le=20000)
    max_item_chars: int = Field(default=120000, ge=1000, le=1000000)
    concurrency: int = Field(default=2, ge=1, le=8)


class ItemRef(BaseModel):
    model_config = {"extra": "forbid"}
    case_id: str = Field(min_length=1, max_length=300)
    bot_slot: int = Field(ge=0, le=3)


class Sample(BaseModel):
    """A reproducible draw. Stratification spreads the sample; it never reveals Judge output."""

    model_config = {"extra": "forbid"}
    size: int = Field(ge=1, le=1000)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    stratify: Literal["category", "none"] = "category"
    balance_outcomes: bool = Field(
        default=False,
        description="Alternate the saved Judge's own passes and failures so the sample contains "
        "ordinary successes and meaningful failures. Changes the sampled base rate, so false "
        "acceptance and false rejection become conditional on it.",
    )


class SourceRef(BaseModel):
    """An assessment ID is resolved to its recorded Black child; it is never a Run ID."""

    model_config = {"extra": "forbid"}
    kind: Literal["blackbox_run", "assurance_assessment"]
    id: str = Field(min_length=36, max_length=36)


class Selection(BaseModel):
    model_config = {"extra": "forbid"}
    source: SourceRef
    items: list[ItemRef] = Field(default_factory=list, max_length=1000)
    sample: Sample | None = None

    @model_validator(mode="after")
    def one_method(self):
        if bool(self.items) == bool(self.sample):
            raise ValueError("Choose explicit items or a seeded sample, not both or neither.")
        return self


class CreateSet(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=120)
    selection: Selection


class AddItems(BaseModel):
    model_config = {"extra": "forbid"}
    expected_set_revision: int = Field(ge=0)
    selection: Selection


class LabelUpdate(BaseModel):
    """Either a verdict or a finite 0-100 score; contradictions and booleans are rejected."""

    model_config = {"extra": "forbid"}
    expected_revision: int = Field(ge=0, description="0 for a blank label")
    verdict: Literal["pass", "fail"] | None = None
    score: float | None = None
    rationale: str = Field(default="", max_length=20000)
    change_reason: str = Field(default="", max_length=2000)

    @field_validator("score", mode="before")
    @classmethod
    def numeric_only(cls, value):
        if isinstance(value, bool) or (value is not None and not isinstance(value, (int, float))):
            raise ValueError("Score must be a number from 0 to 100.")
        if value is not None and not math.isfinite(value):
            raise ValueError("Score must be finite.")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if self.verdict is None and self.score is None:
            raise ValueError("Provide a verdict or a score.")
        if self.score is not None and not 0 <= self.score <= 100:
            raise ValueError("Score must be from 0 to 100.")
        if self.score is not None and self.verdict is not None:
            if (self.score >= 80) != (self.verdict == "pass"):
                raise ValueError("Verdict and score are contradictory (pass means score >= 80).")
        return self

    @property
    def binary(self) -> bool:
        return self.verdict == "pass" if self.verdict else self.score >= 80


class Freeze(BaseModel):
    """Freezing may reserve a held-out subset, split by scenario so repeats stay together."""

    model_config = {"extra": "forbid"}
    expected_set_revision: int = Field(ge=0)
    holdout_percent: float = Field(default=0, ge=0, le=50)
    holdout_seed: int = Field(default=42, ge=0, le=2**31 - 1)


class CloudConsent(BaseModel):
    """Specific consent: this destination and this exact frozen payload."""

    model_config = {"extra": "forbid"}
    endpoint: str = Field(max_length=2048)
    content_hash: str = Field(min_length=64, max_length=64)


class StartEvaluation(BaseModel):
    model_config = {"extra": "forbid"}
    version: int = Field(ge=1)
    judge: JudgeSelection
    fallbacks: list[JudgeSelection] = Field(default_factory=list, max_length=2)
    auto_local_fallback: bool = False
    cloud_consent: CloudConsent | None = None
    max_budget_usd: str | None = None
    timeout: float = Field(default=60, ge=1, le=120)

    @model_validator(mode="after")
    def local_fallbacks_only(self):
        if any(not f.local or not f.fallback for f in self.fallbacks):
            raise ValueError("Fallbacks must be explicitly selected local fallback judges.")
        return self


class ResumeEvaluation(BaseModel):
    model_config = {"extra": "forbid"}
    token: str | None = Field(default=None, max_length=4096)
    fallback_tokens: list[str] = Field(default_factory=list, max_length=2)


class CompatibilityRequest(BaseModel):
    model_config = {"extra": "forbid"}
    model: str = Field(default="", max_length=250)
    url: str = Field(default="", max_length=2048)
    policy: str | None = Field(default=None, max_length=20000)
    scope: str | None = Field(default=None, max_length=10000)


class EvaluatorFingerprint(BaseModel):
    """Scientific evaluator identity. Credentials are deliberately absent."""

    schema_version: int = SCHEMA_VERSION
    requested_model: str
    endpoint: str
    known_model_revision: str = "Not supplied by provider"
    template_hash: str
    validation_hash: str
    generation_hash: str
