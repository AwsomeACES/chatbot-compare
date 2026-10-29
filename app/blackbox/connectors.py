"""Connect to chatbot interfaces and retain bounded conversation evidence."""

import asyncio
import ipaddress
import json
import os
import socket
import time
import uuid
from urllib.parse import urlsplit

import httpx

from . import metering
from .scheduling import Halted, target_call


async def validate_destination(url):
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("Use an HTTP(S) URL without embedded credentials.")
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, p.hostname, p.port or (443 if p.scheme == "https" else 80)
    )
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        docker_host = (
            os.getenv("STUDIO_DOCKER_HOST_ACCESS") == "1"
            and p.hostname == "host.docker.internal"
            and ip.is_private
            and not ip.is_link_local
            and not ip.is_unspecified
            and not ip.is_reserved
        )
        if not (ip.is_global or ip.is_loopback or docker_host):
            raise ValueError(
                "Only public addresses or loopback are allowed; private-network and metadata endpoints are blocked."
            )


async def request_json(client, method, url, **kwargs):
    await validate_destination(url)
    async with client.stream(method, url, **kwargs) as r:
        r.raise_for_status()
        body = bytearray()
        async for chunk in r.aiter_bytes():
            body.extend(chunk)
            if len(body) > 512000:
                raise ValueError("Response exceeded 500 KB limit.")
        if "text/event-stream" in r.headers.get("content-type", ""):
            return parse_chat_stream(body.decode("utf-8"))
        return json.loads(body)


def parse_chat_stream(text):
    """Decode the Reliance token/meta/done SSE contract, never pass HTTP-200 errors."""
    chunks = []
    done = False
    metadata = {}
    for block in text.replace("\r\n", "\n").split("\n\n"):
        event = "message"
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if not data:
            continue
        payload = json.loads("\n".join(data))
        if event == "error":
            raise ValueError(
                "Chat stream error: " + str(payload.get("message", "Unknown error"))[:300]
            )
        if event == "meta":
            metadata.update(payload)
        if event == "token":
            if not isinstance(payload.get("text"), str):
                raise ValueError("Invalid chat stream token.")
            chunks.append(payload["text"])
        if event == "done":
            if payload.get("ok") is not True:
                raise ValueError("Chat stream reported unsuccessful completion.")
            done = True
            metadata.update(payload)
    if not done:
        raise ValueError("Chat stream ended without a successful completion event.")
    answer = "".join(chunks)
    if not answer.strip():
        raise ValueError("Chat stream completed without an answer.")
    return {
        "reply": answer,
        "stream_metadata": metadata,
        "usage": metadata.get("usage"),
        "model": metadata.get("model"),
    }


def field(data, path):
    for key in path.split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


class Connector:
    def __init__(self, target, timeout):
        self.target = target
        self.timeout = timeout
        self.kind = target.kind
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def detect(self):
        t = self.target
        if t.kind == "zip":
            raise ValueError(
                (
                    "ZIP execution is unavailable: this machine has no configured isolated "
                    "sandbox. No uploaded code was "
                    "run."
                )
            )
        await validate_destination(t.url)
        if self.kind != "auto":
            return
        if urlsplit(t.url).path.rstrip("/").endswith("/chat/completions"):
            self.kind = "openai"
            return
        headers = {"Authorization": "Bearer " + t.token.get_secret_value()} if t.token else {}
        async with self.client.stream("GET", t.url, headers=headers) as r:
            if r.status_code != 405:
                r.raise_for_status()
            if "text/html" in r.headers.get("content-type", ""):
                self.kind = "web"
            elif "json" in r.headers.get("content-type", "") or r.status_code == 405:
                self.kind = "rest"
            else:
                raise ValueError(
                    "Could not identify a chat interface. Choose REST, OpenAI-compatible, or web chat explicitly."
                )

    async def conversation(self, case):
        if self.kind == "web":
            return await self.web_conversation(case)
        # Cookies, like history and conversation IDs, belong to one case only.
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=False, trust_env=False
        ) as client:
            return await self.http_conversation(case, client)

    async def http_conversation(self, case, client):
        transcript = []
        resume = case.get("resume_observation") or {}
        prefix = resume.get("transcript", [])
        session = resume.get("session_id") or str(uuid.uuid4())
        history = []
        usage = []
        for turn_index, prompt in enumerate(case["turns"]):
            if case["parallel"]:
                history = []
                session = str(uuid.uuid4())
                client.cookies.clear()
            history.append({"role": "user", "content": prompt})
            if (
                turn_index < len(prefix)
                and prefix[turn_index].get("input") == prompt
                and prefix[turn_index].get("output")
            ):
                transcript.append(prefix[turn_index])
                history.append({"role": "assistant", "content": prefix[turn_index]["output"]})
                usage.append((resume.get("usage") or [None] * len(prefix))[turn_index])
                continue
            t = self.target
            headers = {}
            if t.token:
                headers["Authorization"] = "Bearer " + t.token.get_secret_value()
            if self.kind == "openai":
                if not t.model:
                    raise ValueError("The OpenAI-compatible target needs its model ID.")
                body = {"model": t.model, "messages": history, "stream": False}
            else:
                body = {**t.request_defaults, t.message_field: prompt}
                if t.session_field:
                    body[t.session_field] = session
                if t.history_field:
                    body[t.history_field] = history[:-1]
            started = None
            elapsed = None
            try:

                async def send():
                    nonlocal started, elapsed
                    started = time.perf_counter()
                    try:
                        if self.kind == "openai":
                            return await metering.completion(
                                t.url,
                                body,
                                t.token.get_secret_value() if t.token else "",
                                self.timeout,
                            )
                        async with asyncio.timeout(self.timeout):
                            return await request_json(
                                client, "POST", t.url, headers=headers, json=body
                            )
                    finally:
                        elapsed = time.perf_counter() - started

                async with target_call(t.url):
                    data = await metering.call(
                        send,
                        role="target",
                        model=t.model,
                        alias=t.model_alias,
                        provider=metering.provider_from(t.url),
                        endpoint=t.url,
                        messages=history,
                        turn_index=turn_index,
                        conversation_id=(
                            case.get("id", "") + ":" + str(turn_index)
                            if case.get("parallel")
                            else case.get("id", "")
                        ),
                        local=t.local_model,
                        opaque=self.kind != "openai",
                    )
                path = t.response_field or (
                    "choices.0.message.content" if self.kind == "openai" else ""
                )
                if path:
                    answer = field(data, path)
                else:
                    candidates = [
                        data[k]
                        for k in ("answer", "reply", "response", "message", "text")
                        if isinstance(data.get(k), str)
                    ]
                    if len(candidates) != 1:
                        raise ValueError(
                            "Response field is ambiguous. Enter the exact response JSON field in advanced connection settings."
                        )
                    answer = candidates[0]
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("The configured answer field is empty or not text.")
                answer = answer[:24000]
                if t.session_field and data.get(t.session_field):
                    session = data[t.session_field]
                history.append({"role": "assistant", "content": answer})
                usage.append(data.get("usage"))
                transcript.append(
                    {
                        "input": prompt,
                        "output": answer,
                        "seconds": round(elapsed or 0, 3),
                        "transport": "HTTP",
                        "http_status": 200,
                        "response_metadata": data.get("stream_metadata", {}),
                    }
                )
                from .execution_cache import checkpoint_turns

                checkpoint_turns(case, transcript, usage, session)
            except (metering.BudgetLimit, Halted, asyncio.CancelledError) as exc:
                exc.observation = {"transcript": transcript, "usage": usage, "error": str(exc)}
                raise
            except Exception as e:
                transcript.append(
                    {
                        "input": prompt,
                        "output": None,
                        "seconds": round(elapsed or 0, 3),
                        "error": safe_error(e),
                    }
                )
                return {"transcript": transcript, "error": safe_error(e), "usage": usage}
        return {"transcript": transcript, "usage": usage, "error": None}

    async def web_conversation(self, case):
        from pathlib import Path

        from playwright.async_api import async_playwright

        t = self.target
        transcript = []
        async with async_playwright() as p:
            chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
            browser = await p.chromium.launch(
                headless=True, **({"executable_path": str(chrome)} if chrome.exists() else {})
            )
            context = await browser.new_context(accept_downloads=False, service_workers="block")

            async def guard(route):
                try:
                    if route.request.url.startswith(("data:", "blob:")):
                        await route.continue_()
                        return
                    await validate_destination(route.request.url)
                    await route.continue_()
                except Exception:
                    await route.abort()

            await context.route("**/*", guard)
            page = await context.new_page()
            page.set_default_timeout(self.timeout * 1000)
            try:
                await page.goto(t.url, wait_until="domcontentloaded")
                for turn_index, prompt in enumerate(case["turns"]):
                    prefix = (case.get("resume_observation") or {}).get("transcript", [])
                    if (
                        turn_index < len(prefix)
                        and prefix[turn_index].get("input") == prompt
                        and prefix[turn_index].get("output")
                    ):
                        transcript.append(prefix[turn_index])
                        continue
                    if case["parallel"] and transcript:
                        await context.close()
                        context = await browser.new_context(
                            accept_downloads=False, service_workers="block"
                        )
                        await context.route("**/*", guard)
                        page = await context.new_page()
                        page.set_default_timeout(self.timeout * 1000)
                        await page.goto(t.url)
                    inputs = page.locator(
                        t.input_selector
                        or 'textarea:visible, input[type="text"]:visible, [contenteditable="true"]:visible'
                    )
                    if await inputs.count() != 1:
                        raise ValueError(
                            (
                                "Chat input detection is ambiguous; configure its CSS selector. No "
                                "arbitrary page controls were "
                                "clicked."
                            )
                        )
                    answers = page.locator(
                        t.answer_selector
                        or '[data-message-author-role="assistant"], [data-role="assistant"], .assistant-message, .bot-message'
                    )
                    before = await answers.count()
                    start = None
                    elapsed = None

                    async def send_widget():
                        nonlocal start, elapsed
                        start = time.perf_counter()
                        await inputs.fill(prompt)
                        if t.send_selector:
                            await page.locator(t.send_selector).click()
                        else:
                            await inputs.press("Enter")
                        deadline = time.monotonic() + self.timeout
                        last = ""
                        stable = 0
                        while time.monotonic() < deadline:
                            await asyncio.sleep(0.5)
                            if await answers.count() > before:
                                value = await answers.last.inner_text()
                                stable = stable + 1 if value == last and value.strip() else 0
                                last = value
                                if stable >= 3:
                                    break
                        else:
                            raise ValueError(
                                "No identifiable completed assistant reply. Configure the assistant-message CSS selector."
                            )
                        elapsed = time.perf_counter() - start
                        return {"reply": last}

                    async with target_call(t.url):
                        observed = await metering.call(
                            send_widget,
                            role="target",
                            model=t.model,
                            alias=t.model_alias,
                            provider="web-widget",
                            messages=[
                                {"role": "user", "content": p}
                                for p in case["turns"][: turn_index + 1]
                            ],
                            turn_index=turn_index,
                            conversation_id=(
                                case.get("id", "") + ":" + str(turn_index)
                                if case.get("parallel")
                                else case.get("id", "")
                            ),
                            local=t.local_model,
                            opaque=True,
                        )
                    last = observed["reply"]
                    transcript.append(
                        {
                            "input": prompt,
                            "output": last[:24000],
                            "seconds": round(elapsed or 0, 3),
                            "transport": "browser",
                        }
                    )
                    from .execution_cache import checkpoint_turns

                    checkpoint_turns(case, transcript, [])
                return {"transcript": transcript, "error": None, "usage": []}
            except (metering.BudgetLimit, Halted, asyncio.CancelledError) as exc:
                exc.observation = {"transcript": transcript, "usage": [], "error": str(exc)}
                raise
            except Exception as e:
                return {"transcript": transcript, "error": safe_error(e), "usage": []}
            finally:
                await browser.close()


def safe_error(e):
    from .quota import quota_reason

    if reason := quota_reason(e):
        return reason
    if isinstance(e, httpx.HTTPStatusError):
        return f"Target returned HTTP {e.response.status_code}."
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return "Request timed out."
    if isinstance(e, httpx.RequestError):
        return "Target connection failed."
    return str(e)[:400]
