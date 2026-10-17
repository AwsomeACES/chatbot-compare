"""Single-process scheduling shared by all evaluations on an event loop."""

import asyncio
import contextvars
import math
import time
import weakref
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urlsplit

_current = contextvars.ContextVar("studio_execution", default=None)
_states = weakref.WeakKeyDictionary()


class Halted(Exception):
    pass


def retry_delay(exc):
    response = getattr(exc, "response", None)
    if getattr(exc, "status_code", None) != 429 and getattr(response, "status_code", None) != 429:
        return 0
    value = getattr(response, "headers", {}).get("retry-after", "")
    try:
        delay = float(value)
        if math.isfinite(delay):
            return max(1, delay)
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        return max(1, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return 5


def key(url):
    p = urlsplit(url)
    # Group paths/models on the same host: aliases cannot multiply backend load.
    return (p.hostname or "").lower() + ":" + str(p.port or (443 if p.scheme == "https" else 80))


class Gate:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.pacing = asyncio.Lock()
        self.active = 0
        self.leases = {}
        self.next_start = 0

    @asynccontextmanager
    async def slot(self, runtime):
        async with self.condition:
            await self.condition.wait_for(
                lambda: self.active < min((v[0] for v in self.leases.values()), default=1)
            )
            runtime.check()
            self.active += 1
        try:
            yield
        finally:
            async with self.condition:
                self.active -= 1
                self.condition.notify_all()

    async def pace(self, runtime):
        async with self.pacing:
            runtime.check()
            deadline = self.next_start
            delay = max(0, deadline - time.monotonic())
            if delay:
                await asyncio.sleep(delay)
            # An in-flight 429 may extend the cooldown while this waiter is asleep.
            while self.next_start > deadline:
                deadline = self.next_start
                await asyncio.sleep(max(0, deadline - time.monotonic()))
            runtime.check()
            self.next_start = time.monotonic() + max(
                (v[1] for v in self.leases.values()), default=0
            )

    def cooldown(self, exc):
        delay = retry_delay(exc)
        if delay:
            self.next_start = max(self.next_start, time.monotonic() + delay)

    async def remove(self, ident):
        async with self.condition:
            self.leases.pop(ident, None)
            self.condition.notify_all()


class Traffic:
    """Writer-preferring lock: speed tests run without other Studio run traffic."""

    def __init__(self):
        self.cv = asyncio.Condition()
        self.readers = 0
        self.writer = False
        self.waiting = 0

    @asynccontextmanager
    async def phase(self, exclusive=False):
        acquired = False
        async with self.cv:
            if exclusive:
                self.waiting += 1
            try:
                await self.cv.wait_for(
                    lambda: not self.writer
                    and (self.readers == 0 if exclusive else self.waiting == 0)
                )
                if exclusive:
                    self.writer = True
                else:
                    self.readers += 1
                acquired = True
            finally:
                if exclusive:
                    self.waiting -= 1
                if not acquired:
                    self.cv.notify_all()
        try:
            yield
        finally:
            async with self.cv:
                if exclusive:
                    self.writer = False
                else:
                    self.readers -= 1
                self.cv.notify_all()


class Shared:
    def __init__(self):
        self.traffic = Traffic()
        self.targets = {}
        self.judges = {}
        self.judge_totals = {}


def shared():
    loop = asyncio.get_running_loop()
    if loop not in _states:
        _states[loop] = Shared()
    return _states[loop]


class Runtime:
    def __init__(self, config, stop):
        self.config = config
        self.stop = stop
        self.ident = object()
        self.shared = shared()
        self.registered = []
        for t in config.targets:
            self.register(
                self.shared.targets,
                key(t.url),
                min(
                    config.target_concurrency,
                    config.provider_limits.get(key(t.url), config.target_concurrency),
                ),
                config.request_pause_seconds,
            )
        if config.judge_enabled:
            self.register(self.shared.judge_totals, "all", config.judge_concurrency, 0)
        if config.judge_enabled:
            self.register(
                self.shared.judges,
                key(config.judge_url),
                config.judge_concurrency,
                config.judge_pause_seconds,
            )
        if config.secondary_judge_enabled:
            self.register(
                self.shared.judges,
                key(config.secondary_judge_url),
                config.judge_concurrency,
                config.judge_pause_seconds,
            )

    def register(self, pool, k, limit, pause):
        gate = pool.setdefault(k, Gate())
        gate.leases[self.ident] = (limit, pause)
        if gate not in self.registered:
            self.registered.append(gate)
        return gate

    def check(self):
        if self.stop.is_set():
            raise Halted("Stop requested; no new requests sent.")

    @contextmanager
    def context(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    async def close(self):
        for gate in self.registered:
            await gate.remove(self.ident)

    @asynccontextmanager
    async def target(self, url):
        async with self.shared.targets[key(url)].slot(self):
            yield


@asynccontextmanager
async def target_call(url):
    runtime = _current.get()
    gate = runtime.shared.targets[key(url)] if runtime else None
    if gate:
        await gate.pace(runtime)
    try:
        yield
    except Exception as exc:
        if gate:
            gate.cooldown(exc)
        raise


@asynccontextmanager
async def judge_call(config):
    runtime = _current.get()
    if not runtime:
        yield
        return
    gate = runtime.register(
        runtime.shared.judges,
        key(config.judge_url),
        config.provider_limits.get(key(config.judge_url), config.judge_concurrency),
        config.judge_pause_seconds,
    )
    async with runtime.shared.judge_totals["all"].slot(runtime):
        async with gate.slot(runtime):
            await gate.pace(runtime)
            try:
                yield
            except Exception as exc:
                gate.cooldown(exc)
                raise
