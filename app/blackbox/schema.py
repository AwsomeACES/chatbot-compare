from pydantic import BaseModel, Field, SecretStr, PrivateAttr, model_validator
from typing import Literal
from urllib.parse import urlsplit

CATEGORIES = {
 'hallucination':'Hallucination testing (answer accuracy)', 'bias':'Bias testing (fairness)', 'injection':'Prompt injection',
 'jailbreak':'Multi-turn jailbreak', 'guardrails':'Guardrails testing (safety policy)', 'prompt_leakage':'System prompt leakage',
 'pii':'Personal data leakage', 'toxicity':'Toxicity', 'over_refusal':'Unnecessary refusals',
 'consistency':'Consistency', 'calibration':'Acknowledging uncertainty', 'scope':'Scope adherence',
 'memory':'Conversation memory', 'language':'Language and tone', 'performance':'Performance testing (speed and reliability)',
 'functional':'Functional correctness'}

CATEGORY_DETAILS = {
 'hallucination': {'description':'Check answers against your reference facts for unsupported or contradictory claims.', 'requires':'Running chatbot, reference cases, and a configured AI judge.'},
 'bias': {'description':'Compare equivalent scenarios with different names, pronouns or age references.', 'requires':'Running chatbot and AI judge. Paired starter prompts are included.'},
 'guardrails': {'description':'Check whether the chatbot follows your safety rules and authorization limits.', 'requires':'Running chatbot, your safety policy, and a configured AI judge.'},
 'performance': {'description':'Measure response time, request failures and timeouts using sequential requests.', 'requires':'Running chatbot and speed-test consent. No AI judge is needed.'},
}

class Target(BaseModel):
 name: str = Field(default='My chatbot', min_length=1,max_length=100)
 url: str = Field(default='',max_length=2048)
 kind: Literal['auto','rest','openai','web','zip'] = 'auto'
 archive_id: str = ''
 request_defaults: dict = Field(default_factory=dict)
 message_field: str = 'message'
 response_field: str = ''
 session_field: str = 'conversation_id'
 history_field: str = ''
 model: str = ''
 token: SecretStr | None = None
 input_selector: str = ''
 answer_selector: str = ''
 send_selector: str = ''
 @model_validator(mode='after')
 def validate_url(self):
  if len(str(self.request_defaults))>10000:raise ValueError('Request defaults exceed 10 KB.')
  if self.kind != 'zip':
   p=urlsplit(self.url)
   if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
    raise ValueError('Enter a complete HTTP(S) chat or API URL without credentials in the URL.')
  return self

class Settings(BaseModel):
 _setup_notes: list[str] = PrivateAttr(default_factory=list)
 targets: list[Target] = Field(min_length=1,max_length=2)
 categories: list[str] = Field(default_factory=lambda:list(CATEGORIES))
 cases_per_category: int = Field(default=30,ge=30,le=100)
 references: list[dict] = Field(default_factory=list,max_length=500)
 policy: str = Field(default='',max_length=20000)
 scope: str = Field(default='',max_length=10000)
 judge_url: str = 'http://127.0.0.1:1234/v1/chat/completions'
 judge_model: str = ''
 judge_token: SecretStr | None = None
 consent: bool = False
 judge_consent: bool = False
 performance_consent: bool = False
 request_pause_seconds: float = Field(default=.25,ge=.25,le=15)
 timeout: float = Field(default=20,ge=1,le=60)
 max_minutes: int = Field(default=20,ge=1,le=120)
 latency_budget_seconds: float = Field(default=5,ge=.1,le=60)
 seed: int = 42
 @model_validator(mode='after')
 def check(self):
  self.categories=list(dict.fromkeys(self.categories))
  if not self.categories or any(c not in CATEGORIES for c in self.categories):
   raise ValueError('Choose supported black-box categories.')
  if len(str(self.references))>300000: raise ValueError('References exceed 300 KB.')
  return self
