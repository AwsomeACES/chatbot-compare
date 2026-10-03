# Chatbot Compare: what's built, and what to fix for three-bot comparisons

*Project review · 30 Sep 2026*

A test bench that puts several support chatbots through the same 24 customer questions, grades every answer, and names a winner. It already accepts 2–4 bots per run. The three-bot run from 28 Sep shows where the scoring stops being fair once a third bot is added.

## Done so far

- **Same test, each bot on its own data.** One suite (`suites/store_support.json`) of 24 templated cases across 7 skills: products, grounding, orders, after-sales, safety, multi-turn, language. Each bot gets a profile with its own prices and orders, so VoltKart is asked about its Samsung TV at Rs 47,990 and the Reliance bot about its LG OLED.
- **Three ways to score each answer.** Exact checks (must contain the right fact, must not leak data), a blind AI judge (Claude Opus 5 on Bedrock, rating correctness, helpfulness and tone 1–5 via a forced tool call), and speed (median and p95 seconds per reply).
- **One overall number.** 45% accuracy + 40% judge quality + 15% speed, or 80/20 without the judge. Ranked, with a "too close to call" label under a 3-point margin.
- **Fairness rules.** Skills a bot wasn't designed for count as *not supported*; quota and rate-limit errors count as *blocked*. Both are left out of that bot's score.
- **Five adapters** so almost any bot plugs in through `bots.json`: VoltKart API, generic JSON HTTP, SSE streaming, OpenAI-compatible, and Claude on Bedrock.
- **Dashboard.** Pick bots, run, and watch results arrive; scorecard, grouped bar charts, latency chart, case-by-case transcripts side by side with an "only where bots disagree" filter.
- **Blind arena.** Chat with two anonymous bots, vote, and build an Elo leaderboard.
- **`rejudge.py`** re-grades or re-checks a saved run without calling the bots again.

## Stack

| Layer | What's used |
|---|---|
| Backend | Python 3, FastAPI, Uvicorn, Pydantic v2, python-dotenv. Runs execute in a background thread with a `ThreadPoolExecutor` (`EVAL_CONCURRENCY`, default 4). |
| LLM access | Anthropic Python SDK with Bedrock (`AnthropicBedrockMantle`) using AWS credentials. `httpx2` for plain HTTP and SSE streaming. |
| AI judge | Claude Opus 5 on Amazon Bedrock, medium effort, returning a Pydantic-validated verdict through a tool call. |
| Frontend | Plain HTML, CSS and JavaScript with no build step or framework. Hand-drawn SVG charts. Light and dark themes. |
| Storage | JSON files in `runs/` (one per run, written atomically) and `runs/arena.json` for votes and Elo. |
| Bots under test | VoltKart: FastAPI with tool calling, on Sonnet 5, Haiku 4.5, GPT-5 mini or Nova Pro. Teammate's Reliance bot: LangGraph supervisor with sales, resQ and RAG agents over ChromaDB, SSE output, Gemini 3.6 Flash by default. |

## The three-bot run (20260928-072607)

| # | Bot | Overall | Pass rate | Judge quality | Median | p95 | Cases scored |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | My bot · Haiku 4.5 | 93.5 | 91.3% | 89.1 | 2.7s | 5.4s | 23 |
| 2 | My bot · Sonnet 5 | 90.1 | 95.7% | 97.5 | 4.9s | 8.2s | 23 |
| 3 | Teammate · Gemini | 85.5 | 100% | 90.0 | 9.0s | **38.0s** | **10 (13 blocked)** |

- Haiku wins overall while Sonnet passes more cases and has much better judge quality; the 15% speed weight decides it.
- Gemini shows a 100% pass rate, but on only 10 of 23 cases, so it isn't comparable to the others.
- In the follow-up run (20260928-074327) all 23 Gemini cases were blocked, yet it still appears ranked #3 with an overall score of 0.

## Changes for fair three-bot comparisons

Ordered by how much each one can change who wins.

### 1. Rank all three bots on the same cases — High
*`evaluator.py` · `summarise()`*

Blocked and unsupported cases are dropped per bot, so each bot is scored on a different set. Gemini's 100% came from 10 cases while the Claude bots were scored on 23. **Fix:** compute the ranking on the cases every selected bot completed, show per-bot coverage, and mark a bot "incomplete, not ranked" below about 80% coverage. A bot with 0 scored cases should show "no result" instead of 0.

### 2. Retry rate limits instead of giving up — High
*`evaluator.py` · `_run_case()`, `_execute()`*

With three bots and 4 parallel workers, the Gemini key hit its quota and 13–23 cases were lost. **Fix:** retry 429 / RESOURCE_EXHAUSTED with exponential backoff before marking a case blocked, and add a per-bot `max_concurrency` in `bots.json` so a free-tier key gets 1 worker while Bedrock gets 4. Add a "re-run blocked cases" button that fills gaps in an existing run.

### 3. Measure speed without the bots slowing each other down — High
*`evaluator.py` · `summarise()` speed; `CONCURRENCY`*

Sonnet and Haiku both run on the same VoltKart server (port 8000) and share the worker pool with Gemini, so latency is measured under contention and depends on which bots were picked. Speed is also scored relative to the fastest bot in the run, so adding a third bot changes the other two bots' scores. **Fix:** score speed against fixed targets (for example 100 at 2s or less, 0 at 20s or more) and include p95, since Gemini's 38s tail is the real customer problem. Optionally time replies in a separate one-at-a-time pass.

### 4. Add head-to-head results for each pair — Medium
*`evaluator.py` · `summarise()`; `static/app.js`*

The summary compares the winner only with second place. With three bots you want A vs B, A vs C and B vs C: on how many shared cases each bot beat, tied or lost to the other. **Fix:** add a 3×3 win/tie/loss matrix to the summary and a matrix view to the Results tab. Add a case filter for "one bot differs from the other two".

### 5. Show whether the winner is actually ahead — Medium
*`evaluator.py` · `summarise()`; `static/app.js` · `renderTiles()`*

With 23 cases, a single case moves the pass rate by about 4.3 points, yet the "too close to call" line is a fixed 3 points. **Fix:** bootstrap the overall score over cases to get a range for each bot, call it a tie when the ranges overlap, and support repeating a run 3 times and averaging, since LLM answers vary between runs.

### 6. Let the judge compare the three answers directly — Medium
*`evaluator.py` · `judge()`*

The judge grades each answer alone, and scores bunch near the top (89–97.5), so they separate the bots poorly. It is also a Claude model judging two Claude bots against one Gemini bot, which risks self-preference. **Fix:** add a comparative pass that shows the judge all three answers in shuffled order and asks for a ranking. Run a second judge from another model family on a sample and report how often the two agree. Store the judge prompt version in the run.

### 7. Grow the test suite — Medium
*`suites/store_support.json`*

Several skills have only 2–3 cases, so one miss in multi-turn drops Haiku to 66.7%. Language and multi-turn had no Gemini results at all. **Fix:** aim for 8–10 cases per skill (about 60–70 in total). If the third bot comes from another store or team, add a third profile with its facts and capabilities, and flag skills that fewer than all three bots support.

### 8. Keep the app separate from the model — Medium
*`bots.json`; `static/app.js`*

The three-bot run compared two models of my bot against the teammate's bot on a different model, so it mixes "which app" with "which model". **Fix:** save presets such as "same model, three apps" (all on Sonnet 5, once the teammate's Claude key is set) and "three models, same app", and label the run type on the results page.

### 9. Make the arena handle three bots — Lower
*`app.py` · `arena_message()`, `arena_vote()`*

The arena always picks two bots at random, so with three bots some pairs get far more battles than others, and Elo depends on vote order. **Fix:** rotate through pairs so each gets equal battles, or add a three-column mode where you rank A, B and C. Compute ratings with Bradley–Terry over all votes instead of running Elo. Battles live in server memory and are lost on restart, so save them to disk.

### 10. Make runs reproducible and tested — Lower
*`evaluator.py` · `start_run()`; `rejudge.py`; `static/app.js` · `loadSetup()`*

A run stores bot ids and labels but not their config, model ids, or a hash of the suite, so an old run can't be explained after `bots.json` changes. `rejudge.py` fails with a KeyError if a bot was removed, and writes the file non-atomically. There are no tests. **Fix:** snapshot bot config (without secrets) and the suite hash in each run; add pytest tests for `render`, `run_checks` and `summarise` using a saved three-bot run as a fixture. The dashboard also pre-selects only two bots; let it remember a three-bot preset.

## Suggested order

1. **Trustworthy scores:** shared case set and coverage (1), backoff and per-bot concurrency (2), absolute speed score (3).
2. **Clearer verdict:** pairwise matrix (4), confidence ranges and repeats (5), comparative judge (6).
3. **Breadth:** bigger suite and third profile (7), app vs model presets (8), three-way arena and tests (9, 10).

After step 1, re-run Haiku, Sonnet and Gemini once the Gemini quota resets. That gives a like-for-like baseline to compare against after each later change.
