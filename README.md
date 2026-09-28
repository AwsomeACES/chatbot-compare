# Chatbot Compare

Compare 2–4 chatbots on the same test and find out which one is best, and why.

It was built to compare **my VoltKart bot** (`~/projects/reliance-digital-chatbot`) with **my teammate's
Reliance Digital multi-agent bot** (`~/projects/relience-project-222`), but any chatbot with an HTTP API can be plugged in.

## How the comparison works

1. **Same skills for every bot, each on its own data.** The two bots sell different products, so
   `suites/store_support.json` holds 24 test *templates* (price lookup, unknown product, order tracking,
   prompt injection, follow-up questions, Hindi...) and a **profile** per bot with that bot's own facts.
   `"How much is the {tv}?"` becomes "Samsung 55 inch TV → Rs 47,990" for VoltKart and
   "LG 55 inch OLED → Rs 129,999" for the teammate's bot.
2. **Every answer is scored three ways**
   - *Exact checks*: the reply must contain the right fact, or must not contain leaked data.
   - *AI judge*: Claude Opus 5 (on Bedrock) grades the conversation against a rubric for correctness, helpfulness and tone, 1–5,
     without being told which bot wrote it.
   - *Speed*: seconds per reply (median and 95th percentile).
3. **Winner** = highest overall score: `45% accuracy + 40% judge quality + 15% speed`
   (`80% accuracy + 20% speed` without the judge).
4. **Fairness rules**
   - Skills a bot was not designed for are shown as *not supported* and left out of its score
     (e.g. service tickets exist only in the teammate's bot; phone verification only in VoltKart).
   - Quota / rate-limit errors are shown as *blocked* and left out of the score. Re-run when the quota resets.
   - For a fair *app* comparison, run both bots on the same LLM; otherwise you are also comparing models.
5. **Blind arena**: you chat with two anonymous bots side by side, vote, and votes build an Elo leaderboard.

## Files

| File | What it does |
|---|---|
| `app.py` | FastAPI server: bots, suites, runs, arena API; serves the dashboard |
| `adapters.py` | How to talk to each kind of bot (`voltkart`, `sse_chat`, `http`, `openai_compatible`, `claude_bedrock`) |
| `evaluator.py` | Runs a suite against the bots, checks, AI judge, scoring and winner |
| `bots.json` | The bots to compare (URL, model, which profile of facts they use) |
| `suites/store_support.json` | The shared test cases + each bot's facts |
| `static/` | Dashboard: pick bots, run, scorecard, charts, case-by-case answers side by side, arena |
| `runs/` | Saved results (JSON), plus `arena.json` votes |

## Run it

```bash
# 1. My bot (port 8000)
cd ~/projects/reliance-digital-chatbot && .venv/bin/uvicorn app:app --port 8000

# 2. Teammate's bot (port 8001). CHROMA_PATH replaces the Windows path in its .env.
cd ~/projects/relience-project-222/"relience-project 222"/reliance-project/backend
CHROMA_PATH="$PWD/../reliance-ai-agent/reliance-data/chroma_db" CLAUDE_MODEL=claude-sonnet-5 OPENAI_MODEL=gpt-5-mini \
  ~/projects/chatbot-compare/.bots/reliance222-venv/bin/uvicorn main:app --port 8001

# 3. This app (port 8080)
cd ~/projects/chatbot-compare && .venv/bin/uvicorn app:app --port 8080
```

Open http://localhost:8080. Uses your AWS credentials for Bedrock (the judge and Claude bots).
Env vars: `JUDGE_MODEL` (default `anthropic.claude-opus-5`), `EVAL_CONCURRENCY` (default 4), `BOT_TIMEOUT` (seconds, default 120).

## Adding another bot

Add an entry to `bots.json`. Give it a `profile` from the suite (or add a new profile with that bot's facts):

```json
{"id": "new-bot", "label": "New bot", "profile": "voltkart",
 "type": "http", "url": "http://localhost:9000/chat",
 "body": {"text": "{message}", "session": "{session_id}"}, "reply_path": "answer"}
```
