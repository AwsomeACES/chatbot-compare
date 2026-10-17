"""Shared, evidence-first contracts for independently selectable engines."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from ..blackbox.schema import Settings

Mode = Literal["black", "gray", "white"]


class Evidence(BaseModel):
    kind: Literal["transcript", "code", "log", "configuration", "tool"]
    excerpt: str = Field(max_length=4000)
    file: str = ""
    line: int | None = None
    source_id: str = ""


class Finding(BaseModel):
    mode: Mode
    bot: int = 0
    category: str
    test_id: str
    verdict: Literal["pass", "fail", "not_tested", "exists"]
    severity: Literal["Critical", "High", "Medium", "Low", "Pass"] = "Low"
    confidence: Literal["High", "Medium", "Low"] = "Low"
    score: float | None = Field(default=None, ge=0, le=100)
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: str
    fix: str
    checked: str
    consequence: str
    control: bool | None = None
    tool: str = ""
    tool_version: str = ""
    details: dict = Field(default_factory=dict)
    review: bool = False
    overridden: bool = False

    @model_validator(mode="after")
    def require_evidence(self):
        if self.verdict != "not_tested" and not self.evidence:
            raise ValueError("A measured finding requires evidence.")
        if self.verdict == "not_tested":
            self.score = None
            self.confidence = "Low"
        if not self.overridden:
            self.review = self.review or self.severity == "Critical" or self.confidence == "Low"
        return self


class BotInputs(BaseModel):
    system_prompt: str = ""
    config: str = ""
    tools: str = ""
    knowledge: str = ""
    logs: str = ""
    code: str = ""


class Assessment(BaseModel):
    settings: Settings
    modes: list[Mode] = Field(default_factory=lambda: ["black"], min_length=1, max_length=3)
    inputs: list[BotInputs] = Field(default_factory=list, max_length=4)
    ownership_confirmed: bool = False
    private_cloud_opt_in: bool = False
    upload_retention_days: int = Field(default=0, ge=0, le=30)

    @model_validator(mode="after")
    def validate_consent(self):
        if not self.ownership_confirmed:
            raise ValueError("Confirm ownership or written permission before testing.")
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("Select each engine once.")
        if self.inputs and len(self.inputs) != len(self.settings.targets):
            raise ValueError("Provide one input card per bot.")
        return self


class Engine(Protocol):
    def required_inputs(self) -> dict[str, list[str]]: ...

    def plan(self, inputs: dict) -> list[dict]: ...

    async def run(self, plan: list[dict]) -> list[Finding]: ...


def missing(mode: Mode, bot: int, category: str, test_id: str, reason: str) -> Finding:
    return Finding(
        mode=mode,
        bot=bot,
        category=category,
        test_id=test_id,
        verdict="not_tested",
        explanation=reason,
        checked=test_id.replace("_", " "),
        consequence="There is no evidence for this check; do not treat it as a pass.",
        fix="Supply the missing input or install the named tool, then rerun this check.",
    )
