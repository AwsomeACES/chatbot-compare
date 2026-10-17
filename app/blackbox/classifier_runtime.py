"""One bounded, reusable offline classifier worker per event loop.

Inference timeouts terminate the worker, rather than leave a CPU thread running.
Models stay loaded across successful requests; no model download is performed.
"""

import asyncio
import atexit
import multiprocessing
import os
import weakref
from dataclasses import dataclass, field
from multiprocessing.connection import Connection


def worker(connection: Connection) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from .local_metrics import classify_sync

    try:
        while True:
            case, observation, options = connection.recv()
            try:
                connection.send({"result": classify_sync(case, observation, options)})
            except Exception as exc:
                connection.send({"error": type(exc).__name__})
    except (EOFError, BrokenPipeError):
        return
    finally:
        connection.close()


@dataclass
class Service:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    process: multiprocessing.Process | None = None
    connection: Connection | None = None

    def close(self) -> None:
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
        if self.connection is not None:
            self.connection.close()
        self.process, self.connection = None, None

    async def request(self, case: dict, observation: dict, options: dict) -> dict | None:
        timeout = float(options.get("timeout_seconds", 30))
        async with self.lock:
            if self.process is None or not self.process.is_alive():
                self.close()
                context = multiprocessing.get_context("spawn")
                self.connection, child = context.Pipe()
                self.process = context.Process(target=worker, args=(child,), daemon=True)
                self.process.start()
                child.close()
            try:
                self.connection.send((case, observation, options))
                ready = await asyncio.to_thread(self.connection.poll, timeout)
                if not ready:
                    raise TimeoutError("Local classifier inference deadline")
                message = self.connection.recv()
                if "error" in message:
                    raise ValueError(message["error"])
                return message["result"]
            except BaseException:
                self.close()
                raise


_services: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


async def request(case: dict, observation: dict, options: dict) -> dict | None:
    loop = asyncio.get_running_loop()
    service = _services.setdefault(loop, Service())
    return await service.request(case, observation, options)


def close_all() -> None:
    for service in list(_services.values()):
        service.close()
    _services.clear()


atexit.register(close_all)
