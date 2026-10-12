"""The web_widget adapter against a local fake chat page, in a real headless browser. Skipped when Playwright or a
browser isn't available."""

import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

import adapters
from adapters import BotError

pytest.importorskip("playwright")
CHROME = os.environ.get("CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
pytestmark = pytest.mark.skipif(not CHROME, reason="no Chrome / Chromium for the browser test")

PAGE = """<!doctype html><meta charset="utf-8"><title>Shop chat</title>
<button id="launcher" onclick="document.getElementById('chat').hidden=false">Chat with us</button>
<div id="chat" hidden>
  <div id="log"><div class="msg bot">Hi! How can I help?</div></div>
  <input id="box"><button id="send">Send</button>
</div>
<script>
const log = document.getElementById('log'), box = document.getElementById('box');
function send() {
  const text = box.value; box.value = '';
  log.insertAdjacentHTML('beforeend', '<div class="msg user"></div>'); log.lastChild.textContent = text;
  const reply = document.createElement('div'); reply.className = 'msg bot'; log.appendChild(reply);
  const full = text.includes('price') ? 'The TV costs Rs 47,990.' : 'Sorry, could you rephrase?';
  let i = 0; const t = setInterval(() => { reply.textContent = full.slice(0, ++i * 4); if (i * 4 >= full.length) clearInterval(t); }, 60);
}
document.getElementById('send').onclick = send;
box.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
</script>"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE)
    handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(root), **k)
    server = ThreadingHTTPServer(("localhost", 0), handler)
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}/index.html"
    server.shutdown()


def bot(url, **extra):
    return {"id": "w", "label": "Widget", "type": "web_widget", "url": url, "open_selector": "#launcher",
            "input_selector": "#box", "reply_selector": ".msg.bot", "browser_path": CHROME, "settle_ms": 500,
            "timeout": 15, **extra}


def test_a_streamed_reply_is_read_once_it_settles(site):
    conv = adapters.open_conversation(bot(site, send_selector="#send"))
    try:
        assert conv.send("What is the price of the TV?").text == "The TV costs Rs 47,990."  # greeting not included
        assert conv.send("hmm").text == "Sorry, could you rephrase?"  # only the message after ours
    finally:
        conv.close()
    conv = adapters.open_conversation(bot(site))  # no send button configured: Enter sends
    try:
        assert conv.send("price please").text == "The TV costs Rs 47,990."
    finally:
        conv.close()


def test_a_selector_that_matches_nothing_is_a_clear_error(site):
    with pytest.raises(BotError, match="selector that matches nothing"):
        adapters.open_conversation(bot(site, input_selector="#no-such-box", timeout=3))


def test_web_widget_needs_its_selectors():
    with pytest.raises(BotError, match="missing: input_selector, reply_selector"):
        adapters.validate({"id": "w", "label": "W", "type": "web_widget", "url": "http://x"})
