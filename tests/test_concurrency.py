import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.blackbox import connectors, judge, metering, runner, scheduling
from app.blackbox.schema import Settings, Target


def config(**kw):
    return Settings(
        targets=[Target(url="http://localhost:8711/chat", kind="rest")],
        categories=["injection"],
        consent=True,
        judge_enabled=False,
        custom_cases=[
            dict(
                category="injection",
                name=f"Case {i}",
                turns=[f"Case {i}"],
                expected="No marker",
                checks={"canary": "marker"},
            )
            for i in range(8)
        ],
        **kw,
    )


def reply():
    return {
        "transcript": [{"input": "hello", "output": "safe", "seconds": 0.03}],
        "error": None,
    }


def test_target_limits_across_simultaneous_runs():
    active = 0
    peak = 0
    wider_run_closed = None

    class Bot:
        def __init__(self, target, *a):
            self.restrictive = target.name == "Restrictive run"

        async def detect(self):
            pass

        async def close(self):
            # Hold the stricter lease until all overlapping traffic finishes.
            # Otherwise its legitimate release allows the wider run to use four
            # slots, making a lifetime peak assertion depend on OS scheduling.
            if self.restrictive:
                await wider_run_closed.wait()
            else:
                wider_run_closed.set()

        async def conversation(self, c):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.03)
                return reply()
            finally:
                active -= 1

    async def go():
        nonlocal wider_run_closed
        wider_run_closed = asyncio.Event()
        a = config(target_concurrency=2)
        a.targets[0].name = "Restrictive run"
        b = config(target_concurrency=4)
        results = await asyncio.gather(
            runner.execute(runner.make_run(a), a, Bot),
            runner.execute(runner.make_run(b), b, Bot),
        )
        assert all(r["status"] == "completed" for r in results)
        assert all(r["summary"][0]["tested"] == 8 for r in results)

    asyncio.run(go())
    assert peak == 2 and active == 0


def test_finished_run_releases_its_stricter_target_limit():
    async def go():
        strict = scheduling.Runtime(config(target_concurrency=2), asyncio.Event())
        wider = scheduling.Runtime(config(target_concurrency=4), asyncio.Event())
        release = asyncio.Event()
        two_active = asyncio.Event()
        four_active = asyncio.Event()
        active = 0

        async def call():
            nonlocal active
            async with wider.target(wider.config.targets[0].url):
                active += 1
                if active == 2:
                    two_active.set()
                if active == 4:
                    four_active.set()
                try:
                    await release.wait()
                finally:
                    active -= 1

        tasks = [asyncio.create_task(call()) for _ in range(4)]
        try:
            await asyncio.wait_for(two_active.wait(), 5)
            assert active == 2
            await strict.close()
            await asyncio.wait_for(four_active.wait(), 5)
            assert active == 4
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await strict.close()
            await wider.close()
        assert active == 0

    asyncio.run(go())


def test_judge_limit_pacing_and_retry_are_shared(monkeypatch):
    active = 0
    peak = 0
    starts = []

    async def completion(*a):
        nonlocal active, peak
        starts.append(time.monotonic())
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.35)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"score": 90, "reason": "fixture", "evidence": ["safe"]}
                            )
                        }
                    }
                ]
            }
        finally:
            active -= 1

    async def unmetered(op, **kw):
        return await op()

    monkeypatch.setattr(metering, "completion", completion)
    monkeypatch.setattr(metering, "call", unmetered)

    async def go():
        cfg = config(judge_concurrency=2)
        cfg.judge_enabled = True
        cfg.judge_model = "fixture"
        cfg.judge_consent = True
        rt = scheduling.Runtime(cfg, asyncio.Event())
        try:
            with rt.context():
                await asyncio.gather(
                    *(judge.ask(cfg, {"transcript": [{"output": "safe"}]}) for _ in range(5))
                )
        finally:
            await rt.close()

    asyncio.run(go())
    assert peak == 2 and active == 0
    assert all(b - a >= 0.24 for a, b in zip(starts, starts[1:]))


def test_speed_exclusive_across_runs_and_no_quality_overlap():
    active = 0
    seen = []

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, c):
            nonlocal active
            active += 1
            seen.append((c["category"], active))
            try:
                await asyncio.sleep(0.02)
                return reply()
            finally:
                active -= 1

    async def go():
        quality = config()
        speed = Settings(
            targets=quality.targets,
            categories=["performance"],
            cases_per_category=3,
            consent=True,
            performance_consent=True,
        )
        runs = await asyncio.gather(
            runner.execute(runner.make_run(quality), quality, Bot),
            runner.execute(runner.make_run(speed), speed, Bot),
            runner.execute(runner.make_run(quality), quality, Bot),
        )
        assert all(r["status"] == "completed" for r in runs)

    asyncio.run(go())
    assert any(cat == "injection" and n > 1 for cat, n in seen)
    assert all(n == 1 for cat, n in seen if cat == "performance")


def test_real_connector_pacing_not_part_of_latency_and_sessions_isolated(monkeypatch):
    observed = []
    durations = []

    async def request(client, method, url, **kw):
        if kw["json"]["message"] == "first":
            assert not client.cookies.get("fixture-session")
            client.cookies.set("fixture-session", kw["json"]["conversation_id"])
        else:
            assert client.cookies.get("fixture-session") == kw["json"]["conversation_id"]
        started = time.perf_counter()
        observed.append((time.monotonic(), kw["json"], client))
        await asyncio.sleep(0.015)
        durations.append(time.perf_counter() - started)
        return {"answer": "safe"}

    async def unmetered(op, **kw):
        return await op()

    monkeypatch.setattr(connectors, "request_json", request)
    monkeypatch.setattr(metering, "call", unmetered)

    async def go():
        cfg = config()
        rt = scheduling.Runtime(cfg, asyncio.Event())
        # This test measures pacing/session isolation, not timeout behavior.
        # Leave room for Windows scheduling and HTTP client initialization.
        client = connectors.Connector(cfg.targets[0], 30)
        try:
            with rt.context():
                cases = [
                    dict(id=str(i), turns=["first", "second"], parallel=False) for i in range(2)
                ]
                return await asyncio.gather(*(client.conversation(c) for c in cases))
        finally:
            await client.close()
            await rt.close()

    results = asyncio.run(go())
    assert all(result["error"] is None for result in results)
    assert len(durations) == 4
    assert sorted(t["seconds"] for r in results for t in r["transcript"]) == pytest.approx(
        sorted(durations), abs=0.02
    )
    assert all(b[0] - a[0] >= 0.24 for a, b in zip(observed, observed[1:]))
    ids = {row[1]["conversation_id"] for row in observed}
    assert len(ids) == 2
    assert len({id(row[2]) for row in observed}) == 2
    assert all(
        [r[1]["message"] for r in observed if r[1]["conversation_id"] == ident]
        == ["first", "second"]
        for ident in ids
    )


def test_stop_does_not_dispatch_queued_cases_or_leak_tasks():
    calls = 0
    active = 0

    class Bot:
        def __init__(self, *a):
            pass

        async def detect(self):
            pass

        async def close(self):
            pass

        async def conversation(self, c):
            nonlocal calls, active
            calls += 1
            active += 1
            try:
                await asyncio.sleep(0.05)
                return reply()
            finally:
                active -= 1

    async def go():
        cfg = config(target_concurrency=1)
        run = runner.make_run(cfg)
        stop = asyncio.Event()
        runner.ACTIVE[run["id"]] = stop
        task = asyncio.create_task(runner.execute(run, cfg, Bot))
        await asyncio.sleep(0.02)
        stop.set()
        result = await task
        assert result["status"] == "stopped" and result["id"] not in runner.ACTIVE
        assert any(c["results"][0]["transcript"] for c in result["cases"])

    asyncio.run(go())
    assert calls == 1 and active == 0


def test_api_allows_multiple_runs_but_caps_and_rejects_duplicate_resume(monkeypatch):
    import app.blackbox_app as api

    async def idle(*a):
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "execute", idle)
    with TestClient(api.app) as client:
        h = {"X-Studio-Request": "1"}
        payload = config().model_dump(mode="json")
        payload["ownership_confirmed"] = True
        ids = []
        for _ in range(api.MAX_ACTIVE_RUNS):
            response = client.post("/api/blackbox/runs", json=payload, headers=h)
            assert response.status_code == 200
            ids.append(response.json()["id"])
        assert client.post("/api/blackbox/runs", json=payload, headers=h).status_code == 409
        assert (
            client.post(f"/api/blackbox/runs/{ids[0]}/resume", json=payload, headers=h).status_code
            == 409
        )
    for ident in ids:
        runner.ACTIVE.pop(ident, None)


def test_cancelled_writer_does_not_block_other_runs():
    async def go():
        traffic = scheduling.Traffic()
        async with traffic.phase():

            async def write():
                async with traffic.phase(True):
                    pass

            task = asyncio.create_task(write())
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with asyncio.timeout(0.5):
            async with traffic.phase():
                pass

    asyncio.run(go())


def test_rate_limit_retry_after_and_connection_cleanup():
    import sqlite3

    import httpx

    from app import database

    error = httpx.HTTPStatusError(
        "quota",
        request=httpx.Request("POST", "http://localhost/chat"),
        response=httpx.Response(429, headers={"Retry-After": "12"}),
    )
    gate = scheduling.Gate()
    now = time.monotonic()
    gate.cooldown(error)
    assert gate.next_start >= now + 11.9
    with database.connect() as connection:
        connection.execute("SELECT 1")
    database.close()
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
