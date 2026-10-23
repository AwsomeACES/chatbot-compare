# Bias, governance and execution guide

Start the Studio with `./start.sh` on macOS/Linux, or `powershell -ExecutionPolicy Bypass -File .\run.ps1` on Windows. Python 3.12+ is required. Existing history is kept.

## Ten categories; nine Bias sub-tests

New runs have ten top-level category bars. Bias contains gender, racial/ethnic, age, socioeconomic, cultural, cognitive/confirmation, media, selection and algorithmic/AI disparity. Editable neutral prompts and subtype tags are in `app/studio/bias-v1.json`; protocol settings, weights, repeats, judge choices and execution limits are in `app/studio/settings.json`. Change the version when changing prompts.

The first five cases are counterfactual pairs. Both prompts use a fresh session and differ only in the declared attribute. Cognitive pairs use opposite leading beliefs; media pairs use the same fictional facts and requested perspectives; selection probes use tiny self-selected samples. Legitimate personalization and requested perspective differences are not automatically discrimination.

Each repeat makes a new bot conversation. Bias has eight conversational sub-tests plus one derived record. With three repeats, each bot has 51 conversation records plus three derived records (54 outcomes). Paired and multi-turn conversations contain more than one message. No request is sent for the derived record.

The Bias bar averages the eight measured subtype scores across all planned repeats, with Not tested contributing zero. The algorithmic score is the mean of five counterfactual fairness scores; its disparity index is 100 minus that mean. It is disclosed separately and does not double-weight Bias. Missing pair scores prevent the derived record from being scored. This cannot inspect training data or establish population-level fairness.

Every subtype includes its specific name, severity, reason and side-by-side source replies. English refusal, length and sentiment signals are only descriptive proxies. They are computed before the LLM judge, whose presentation order is randomized reproducibly; both replies must support the evidence. Duplicate text may legitimately support both replies. Failures with a known canary stop before paid judgment.

## Governance

Open Governance from the results or header. Each saved run has bot/judge cards, same-family warnings, binary pass/fail judge agreement (threshold 80), review flags and an integrity panel. Overrides require a reason, preserve the original verdict, log old/new scores and show an Overridden badge.

Audit entries are hash chained and appended to a separate SQLite journal. Changed payloads and report-tail truncation are detectable against the anchor. Legacy entries remain unverified. This is not a digital signature: an administrator who replaces the entire database and its backups can replace the anchor. Crash recovery catches up durable journal entries written after the last checkpoint; edited history is quarantined rather than silently accepted.

Reproduce creates a new run with the saved protocol, config, seed and price snapshot. It uses fresh bot calls, not a previous run's response cache. Re-enter original cloud/target credentials if needed; keys are not saved in reports or browser storage. Provider aliases, external bot state and nondeterministic services can still change outputs.

JSON and PDF exports redact email/phone/SSN/key patterns. This baseline may miss names, addresses and other contextual PII; inspect before sharing. Original local evidence remains available for verification. Redacted audit payloads no longer recompute their original hashes; exports explicitly carry the source-integrity result rather than claiming the redacted chain verifies.

Retention is opt-in: zero keeps results until deletion; a positive number expires completed results, usage, caches, journal and generated PDF after that many days. Cleanup runs hourly and at startup. Active runs and saved baselines are protected. Delete-run removes the same local data; downloaded copies and shared uploads are not remotely erased.

Mappings in `app/studio/governance.json` are informational engineering themes, not certification, legal advice or a compliance determination. Sources: [NIST](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook), [ISO](https://www.iso.org/standard/42001), [EU legislation](https://eur-lex.europa.eu/eli/reg/2024/1689/oj).

## Judge calibration with human labels

Open **Calibrate a judge on saved conversations** in Results. Select saved conversations (an assessment resolves to its recorded Black Run), then label each one yourself; labels start blank and original judge scores and reasons are hidden, although you may have seen them earlier. Changing a label keeps the earlier revision and needs a written reason. Freeze a version, then evaluate it with a judge: only the saved conversation and rubric are sent, no bot is called and your labels are never sent. Cloud judges need explicit consent for that payload and destination; private data stays local by default.

Agreement counts matching pass/fail decisions (80 and above passes) over validly judged labeled items. Provider failures, missing consent and malformed output remain Not tested and are counted, never dropped from the picture. A fallback model is evaluated separately and never inherits the requested judge's status. Warnings appear on Evaluate and Governance for uncalibrated, stale, incomplete, insufficient or not-aligned states. Calibration never changes a Finding, score, winner or the model-to-model Judge agreement shown above. Deleting the source run, or its retention expiry, removes the copied conversations and invalidates the calibration; deleting a set removes its evaluations, usage rows and audit chain.

Exports are redacted JSON or Markdown with labels, evaluator identity, policy, results, disagreement evidence, costs and limitations. Provider-returned model names are not guaranteed immutable revisions, so silent upstream changes are not detected.

## Caches, speed and optional local classifiers

Bot cache keys include run ID, bot configuration, case, repeat index and prompt hash. Different repeats and new runs always call the bot afresh. Rejudging/resuming the same observation reuses its durable evidence. Judge caches include model/endpoint, exact request/prompt hash and transcript hash; directional comparisons retain both presentation orders.

Cases, repeats, targets and independent judge models run concurrently. Global and per-provider gates bound traffic; Retry-After pacing and backoff apply. Legacy speed checks remain exclusive/sequential for fair latency. Short-window batches have strict item IDs and per-item evidence validation; malformed batches fall back to individual judgment. Batch requests are metered once as shared evaluation overhead, with all constituent case IDs audited. Bot and evaluation cost remain separate; unavailable prices/usage remain Unknown. Planning estimates are approximate and exclude fallback/retry overhead; batching may be optimistic when arrivals are sparse.

Deterministic checks and PII/refusal/length screening run first. Optional HHEM and Qwen3Guard adapters use only preinstalled model folders and never download models. Configure `local_classifiers` in the settings file after installing optional evaluation dependencies. HHEM needs its reviewed local custom code explicitly enabled; Qwen3Guard uses greedy response classification. A killable offline worker bounds inference and keeps loaded models for subsequent cases. Missing dependencies/models or timeouts fall through to the selected judges and are recorded. HHEM needs supplied reference text; Qwen Safe does not establish compliance with a custom safety policy. Local classifier scores remain estimates and are review flagged. No model integration/accuracy claim follows from unit tests.

Sources: [HHEM model card](https://huggingface.co/vectara/hallucination_evaluation_model), [Qwen3Guard model card](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B).

Live per-bot/category progress uses server-sent events with polling as a durable fallback. Reports include cumulative active runtime, summed bot latency and overlapping case-work time. These are not all the same measurement. Checkpointed active time is retained on resume.

The simulated standard-suite benchmark in `tests/test_speed_cache.py` checks all live cases and derived outcomes against the pinned `app/studio/benchmark.json` baseline plus 20%. The initial Windows median was 1.00 s (three runs). This is a runner regression budget, not a live-provider speed guarantee; host contention can affect wall-clock CI tests. Cross-platform execution remains subject to the existing CI matrix and actual host validation.
