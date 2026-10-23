# Choose the evidence you have

Start with **Black**: paste a running chatbot link and choose a judge. The original ten-category comparison, repeat controls, transcripts and separate bot/judge costs remain available in the Black results tab.

Optionally tick **Gray** and upload a system prompt, configuration, tools, text knowledge documents or structured logs. Upload cards show how many checks have their input. Missing input, unavailable models and missing correlation data produce **Not tested**, with reasons. Gray requests share the existing target/provider limits with Black.

Tick **White** to upload a source ZIP or import a public GitHub repository. Code is **never started, imported or built**. White uses a separate read-only scanner sandbox with no network. It does not start a bot from its ZIP. For Black/Gray conversations you still need a running chat link. Private repositories can be supplied as source ZIPs. Remove dependencies and generated files before creating the ZIP.

Before starting, confirm that you own the bots/code or have written permission. The confirmation is recorded. Gray review defaults to local Ollama; cloud review of redacted Gray inputs requires a separate opt-in for that run. White never sends code to an LLM. Installed-only local fallback may change the judge, never the chatbot's provider/model. Every fallback is recorded; a missing chatbot API cannot be repaired by changing its judge.

## Check readiness first

Open **Check readiness before starting** on Evaluate. Each planned check shows **Ready**, **Needs input**, **Tool unavailable** or **Not applicable**, with the reason and next step. Ready means the check can be attempted, not that it will pass. For a source ZIP, Studio reads only the file list and small dependency files; it never extracts or runs the code for this step. Control checks can at most find a declaration from source text. The readiness report is saved with the test.

## Read the results

Combined links findings by **bot and category**, not proven causal dataflow. A declaration in code/config is only **exists**. It becomes **Defended** only with passing behavioral evidence. Failures plus a code/config gap produce **Confirmed risk**; a declared control plus failed behavior produces **Control exists but isn't working**. No cause is invented for a failure without supporting code/config evidence.

Basic/Standard/Full describe the selected evidence modes; they are not certifications. Missing evidence and low-confidence estimates prevent a launch-ready verdict. Critical and low-confidence findings enter the review queue. A false-positive decision needs a written reason and keeps the original finding and old/new verdict in the audit log.

Counts are kept apart: **processed** (the check ran), **measured** (passed or needs attention), **declarations only**, **not verified** and **waiting for review**. Each unverified check says whether the cause is information missing from the bot's files, a Studio limitation, a missing input or an interrupted test, and lists the evidence needed and the next test. Older saved tests get the same explanation without being re-run or changed. **Download list for a teammate** (More actions) exports these unresolved checks as Markdown; the PDF carries the same guidance.

Every finding has four short parts and its evidence. Interface headings and guidance are in English. Original judge explanations, prompts and evidence retain their original language.

Unknown model/price/usage stays **Unknown**. A small positive amount displays **<$0.0001**; local calls display **$0 (local)** only when there is no compute charge. Historical uploaded telemetry is labeled separately and is not added again to benchmark bills.

## Private inputs and canary logs

Logs are reduced to allowlisted tool, model, usage and correlation fields, and common PII/credential patterns are redacted **before** analysis/storage. Redaction is a baseline, not a contextual anonymizer; inspect exports before sharing. Source uploads necessarily contain the submitted code until cleanup, but secret findings never persist full detected credentials or secret-containing lines. Scanner stdout is bounded, Gitleaks uses full redaction, and stderr is discarded.

Uploads default to deletion after a run; a retention setting can keep them for up to 30 days. Unused uploads expire after 24 hours. Shared inputs remain until the other active/retained assessment releases them. Findings, masked excerpts, hashes and audit history remain with the saved report until the report is deleted. Linked Black history is separately deletable. Reproducing a run after input deletion requires re-uploading the identical inputs and re-entering credentials.

The canary is synthetic, not a real secret or customer's phone. Its chat includes the assessment run ID. Logs uploaded before that chat cannot establish its logging behavior. After the chat, upload new JSON/JSONL/OTel logs, then choose **Attach updated canary logs** on the matching bot card. Only records correlated to that run ID can score this check; old canaries cannot become a new pass/fail.

## Optional AI explanation of White-box results

On a finished White-box test, open **Ask an AI judge to explain the White-box results**. The judge receives only the masked reasons and excerpts already in the report, must return one entry per check ID with quotes copied exactly from them, and is rejected otherwise. Local judges are used unless you tick the cloud box for that one request. Every attempt, including rejected output and unknown billing, is recorded. The explanation never changes a result or a review.

## Runtime checks from a test environment

Source files can only show declarations. Four Gray-box checks measure behavior from structured records that you export from an **approved test environment** after a test starts: runtime tool permissions, session expiry, model used and timeouts/retries. Every record must carry the test's `run_id` and a `check` name (`tool_permissions`, `retention`, `timeouts_retries`; model metadata needs only `run_id` and `gen_ai.response.model`). Records from another run or without a run ID are excluded and counted. Upload the file, then choose **Attach updated test logs** for the saved test.

- Tool permissions: `principal`, `resource_owner`, `tool`, `tool_executed`. A pass needs an unauthorized attempt that did not run and an authorized call that did. What the bot said is ignored.
- Session expiry: declare `retention_ttl_seconds` in the Gray-box configuration; records need `session_ref`, `session_created_at`, `observed_at` (number or ISO time) and `session_present`.
- Model used: declare `expected_model` (or the bot's model field). Missing metadata stays Not tested.
- Timeouts and retries: declare `timeout_seconds` and `max_retries`; records need `stage=upstream_attempt` with `status_code` or `injected_delay_ms` from a slow/error provider stub, and one `stage=bot_response` with `elapsed_ms`.

Tolerances are in `runtime_policy` in `app/studio/gray-v1.json`. Use synthetic users and sessions only; never real customer data. Studio's own fixture tests check this logic and say nothing about a real bot.

## Optional scanner setup (maintainer)

Docker is only required for White scanner isolation; Black and Gray do not require it. Install Docker yourself, then provision these **trusted scanner images**, separately from any submitted source:

```sh
docker build -f Dockerfile.scanners -t studio-source-scanners:1 .
docker pull zricethezav/gitleaks:v8.24.2
docker pull semgrep/semgrep:1.116.0
docker pull ghcr.io/google/osv-scanner:v1.9.2
docker pull aquasec/trivy:0.61.1
```

The selected revisions are pinned in `app/studio/scanners.json`. Runs never auto-pull images. The runtime version is checked and the inspected image content ID is executed/recorded. Scanner processes have 512 MB RAM, one CPU, 64 PIDs, bounded output, a 60-second scan timeout, a read-only source mount and temporary no-exec storage. Timed-out containers are removed by their random name. Uploaded ignore files cannot disable Studio rules.

Check readiness offline with `python scripts/prepare_scanner_data.py check --zip <source.zip>`. To build a package-scoped OSV snapshot for one bot, download the official ecosystem `all.zip` yourself, then run `python scripts/prepare_scanner_data.py scope --zip <source.zip> --full-db PyPI=<all.zip> --out runtime/scanner-databases/osv-<name>` and point `STUDIO_SCANNER_OSV_DATABASE` at it. The script never downloads anything and refuses to overwrite an existing folder.

OSV needs a prepared offline database under `runtime/scanner-databases/osv`; Trivy needs its database/check bundle under `runtime/scanner-databases/trivy`. Provision/update these using the pinned tools **outside** an evaluation, then mount them read-only. No database means Not tested, not a clean vulnerability scan. Filesystem/container-configuration scanning is supported; uploaded container images are not built or started. The custom control rules (`controls-v2`) combine text rules with Python `ast` parsing; they never import or run the code. A handler for an upstream provider's `RateLimitError` is reported but is not counted as inbound access control. They identify declarations, not comprehensive control flow or complete CI execution.

The HHEM adapter needs separately installed, reviewed offline weights and configuration in `app/studio/settings.json`. Its dedicated Gray metric is Not tested when unavailable; a rubric estimate is never labeled an HHEM score. The setup does not download models automatically.

Scanner image/DB execution, real HHEM accuracy and native macOS/Linux execution still require integration validation. Windows offline tests do not prove these integrations work.

References: [Gitleaks](https://github.com/gitleaks/gitleaks), [Semgrep local rules](https://docs.semgrep.dev/running-rules), [OSV offline mode](https://github.com/google/osv-scanner/blob/main/docs/offline-mode.md), [Trivy air gap](https://www.trivy.dev/docs/v0.55/guide/advanced/air-gap/). The [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) and [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) mapping is informational engineering guidance, not certification or legal compliance.

## Verified White scanner run and Windows/WSL notes

The six scanner tools were actually run against a Python/Next.js source ZIP on Windows with Ubuntu WSL on 2026-10-15. This verifies that integration on this host, not native macOS/Linux behavior or comprehensive security coverage.

Windows may use `STUDIO_SCANNER_WSL_DISTRO=Ubuntu` to route only Docker commands into an installed WSL engine. No TCP daemon port is opened. Native Docker remains the default when this variable is absent. Source/rules stay read-only and network remains disabled during scans. Only the public Trivy database gets a disposable writable copy, capped at 2 GiB; the shared DB stays read-only.

OSV 1.9.2 uses `scan --experimental-offline --experimental-all-packages`. It has a configurable 2 GiB RAM / 240-second cap (other scanners default 512 MiB / 60 seconds); cold-start metadata/version checks use separate 30/45-second limits. Large public databases may need a package-scoped snapshot from the official offline inventory. `STUDIO_SCANNER_OSV_DATABASE` can name that trusted snapshot directory. A scope.json coverage manifest and filtered DB hashes are required, and every package in the final OSV report must be covered. A different bot with an uncovered dependency is Not tested until a matching snapshot is provisioned. Package inventory alone is never accepted as a vulnerability pass.

The result page distinguishes **checks processed by scanners** from **passes**. No-match controls are completed text scans with insufficient evidence, so their verdict remains Not tested. Exists means a declaration was observed, not that its control works. Trivy filesystem dependencies may be inspected even when no Dockerfile exists; no submitted image is built. OSV and Trivy issue counts can overlap. One existing PII regex can over-redact public CVE identifiers; advisory redaction needs further context-aware refinement.
