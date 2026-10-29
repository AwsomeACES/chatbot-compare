"""Explicit adapters: frameworks must receive these models for every model role.
No global SDK monkeypatching. Inactive frameworks do not imply measured calls.
"""

import asyncio
import contextvars
import json
from concurrent.futures import ThreadPoolExecutor

from . import metering


def synchronous(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, awaitable).result()


class ModelAdapter:
    def __init__(self, config, role="judge"):
        if role not in metering.ROLES:
            raise ValueError("Unknown model role.")
        self.config = config
        self.role = role

    def get_model_name(self):
        return self.config.judge_model

    def load_model(self):
        return self

    async def a_generate(self, prompt, schema=None):
        if not self.config.judge_consent:
            raise ValueError("Judge data-sharing consent is missing.")
        if metering._context.get() is None:
            raise ValueError("Framework calls require a metered run/case context.")
        messages = (
            prompt if isinstance(prompt, list) else [{"role": "user", "content": str(prompt)}]
        )
        if schema is not None:
            messages.append(
                {
                    "role": "system",
                    "content": "Return JSON matching this schema: "
                    + json.dumps(schema.model_json_schema()),
                }
            )
        body = {
            "model": self.config.judge_model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1500,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}

        async def request():
            return await metering.completion(
                self.config.judge_url,
                body,
                self.config.judge_token.get_secret_value() if self.config.judge_token else "",
                self.config.timeout,
            )

        data = await metering.call(
            request,
            role=self.role,
            model=self.config.judge_model,
            alias=self.config.judge_model_alias,
            provider=metering.provider_from(self.config.judge_url),
            endpoint=self.config.judge_url,
            messages=messages,
            local=self.config.judge_local_model,
        )
        text = data["choices"][0]["message"]["content"]
        return schema.model_validate_json(text) if schema is not None else text

    def generate(self, prompt, schema=None):
        return synchronous(self.a_generate(prompt, schema))


def deepeval_model(config, role="judge"):
    from deepeval.models import DeepEvalBaseLLM

    class MeteredDeepEval(ModelAdapter, DeepEvalBaseLLM):
        def __init__(self):
            ModelAdapter.__init__(self, config, role)

    return MeteredDeepEval()


def deepteam_models(config):
    # Supply both; omitting a simulator/evaluator would allow a framework default to escape metering.
    return {
        "simulator_model": deepeval_model(config, "attacker"),
        "evaluation_model": deepeval_model(config, "judge"),
    }


def garak_generator(config):
    from garak.attempt import Message
    from garak.generators.base import Generator

    model = ModelAdapter(config, "attacker")

    class MeteredGenerator(Generator):
        """Studio counts each Garak-dispatched model call."""

        supports_multiple_generations = False
        parallel_capable = False  # Process pools cannot inherit a per-case ContextVar safely.

        def __init__(self):
            super().__init__(name=config.judge_model)

        def _call_model(self, prompt, generations_this_call=1):
            messages = self._conversation_to_list(prompt)
            return [Message(model.generate(messages)) for _ in range(generations_this_call)]

    return MeteredGenerator()


async def local_call(operation, model, role, messages, tokenizer=None):
    if role not in ("hallucination_detector", "guard", "embedding", "judge"):
        raise ValueError("Unsupported local metric role.")
    if metering._context.get() is None:
        raise ValueError("Local metric calls require a metered context.")
    return await metering.call(
        operation,
        role=role,
        model=model,
        messages=messages,
        provider="local",
        local=True,
        tokenizer=tokenizer,
    )
