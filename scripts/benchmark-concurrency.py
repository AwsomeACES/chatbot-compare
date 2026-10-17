"""Synthetic scheduler benchmark; never sends target or paid judge requests."""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def benchmark():
    from app.blackbox import runner, scheduling
    from app.blackbox.schema import Settings, Target

    async def fixture_judge(config, case, observation):
        async with scheduling.judge_call(config):
            await asyncio.sleep(0.4)
        return {
            "score": 90,
            "reason": "Synthetic scheduler fixture; not a real bot evaluation.",
            "evidence": ["synthetic reply"],
            "estimated": True,
        }

    class Bot:
        def __init__(self, target, *a):
            self.target = target

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, case):
            async with scheduling.target_call(self.target.url):
                start = time.perf_counter()
                await asyncio.sleep(0.4)
                elapsed = time.perf_counter() - start
            return {
                "transcript": [
                    {"input": case["turns"][0], "output": "synthetic reply", "seconds": elapsed}
                ],
                "error": None,
            }

    original = runner.evaluate
    runner.evaluate = fixture_judge
    try:
        durations = []
        totals = []
        for concurrency in (1, 4):
            config = Settings(
                targets=[Target(url="http://localhost:8999/chat")],
                categories=["hallucination", "bias", "guardrails", "injection"],
                policy="Synthetic fixture policy",
                consent=True,
                judge_model="synthetic",
                judge_consent=True,
                case_concurrency=concurrency,
                target_concurrency=concurrency,
                judge_concurrency=concurrency,
            )
            result = await runner.execute(runner.make_run(config), config, Bot)
            assert result["status"] == "completed" and all(
                c["results"][0]["status"] == "passed" for c in result["cases"]
            )
            durations.append(result["duration_seconds"])
            totals.append(result["summary"][0]["tested"])
        return {
            "type": "synthetic scheduler benchmark, not chatbot quality",
            "cases_per_run": totals,
            "simulated_target_seconds": 0.4,
            "simulated_judge_seconds": 0.4,
            "request_gap_seconds": 0.25,
            "sequential_seconds": durations[0],
            "parallel_seconds": durations[1],
            "speedup": round(durations[0] / durations[1], 2),
            "provider_calls": 0,
            "limitation": (
                "One simulated target exchange and one judge exchange per case; does not "
                "benchmark real multi-turn bot/provider "
                "behavior."
            ),
        }
    finally:
        runner.evaluate = original


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="studio-concurrency-benchmark-") as runtime:
        os.environ["STUDIO_RUNTIME"] = runtime
        result = asyncio.run(benchmark())
    print(json.dumps(result, indent=2))
