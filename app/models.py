from typing import Literal
from pydantic import BaseModel, Field, SecretStr, model_validator
from .config import MAX_CASES

CATEGORIES = ['static', 'unit', 'coverage', 'functional', 'security', 'injection', 'guardrails', 'hallucination', 'bias', 'multiturn', 'language', 'performance']

class RunConfig(BaseModel):
    categories: list[Literal['static','unit','coverage','functional','security','injection','guardrails','hallucination','bias','multiturn','language','performance']] = ['static', 'security']
    target_url: str = Field(default='', max_length=2048)
    target_consent: bool = False
    endpoint: str = Field(default='', max_length=512)
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] = 'POST'
    request_field: str = 'message'
    response_field: str = 'answer'
    session_field: str = 'conversation_id'
    timeout: float = Field(default=10, ge=1, le=60)
    iterations: int = Field(default=10, ge=1, le=min(MAX_CASES, 200))
    concurrency: int = Field(default=2, ge=1, le=5)
    requests_per_second: float = Field(default=2, ge=0.1, le=5)
    duration_limit: int = Field(default=60, ge=1, le=120)
    language: Literal['English','Hindi','Hinglish'] = 'English'
    dataset: list[dict] = Field(default_factory=list, max_length=MAX_CASES)
    safety_policy: str = Field(default='Never disclose synthetic secrets or execute unauthorized tools.', max_length=5000)
    model: str = Field(default='', max_length=100)
    api_key: SecretStr | None = None
    judge_consent: bool = False
    execution_consent: bool = False
    performance_consent: bool = False
    startup_command: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def unique_categories(self):
        self.categories = list(dict.fromkeys(self.categories))
        if not self.categories:
            raise ValueError('Select at least one test category')
        if self.startup_command:
            raise ValueError('Automatic application startup is unavailable. Inspect and start a trusted app manually, then enter its local URL.')
        if len(str(self.dataset)) > 200000:
            raise ValueError('Dataset exceeds 200 KB')
        return self


