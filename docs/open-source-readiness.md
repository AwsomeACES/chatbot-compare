# Open-source release readiness

Purpose: record the release gate status with evidence, and name what blocks publication.
Owner: AI Agent Studio maintainers.
Last updated: 2026-11-09.

This is a working ledger, not a release certificate. A gate is **Met** only when a command was actually run and its result recorded. "Not tested" is a real state here too.

## Contents

- [Intended release](#intended-release)
- [Release gates](#release-gates)
- [What this candidate does not establish](#what-this-candidate-does-not-establish)
- [Private material review](#private-material-review)
- [Owner decisions still required](#owner-decisions-still-required)

## Intended release

Make AI Agent Studio easy for another person to install locally, evaluate a bot they own, inspect evidence, export results and contribute improvements. Preserve Black-box, Gray-box and White-box testing, Judges, Governance and metering. Keep the English UI simple while keeping detailed evidence reachable.

The first release is a **local, single-user application** bound to loopback. Shared internet hosting is a separate project and not a prerequisite; see [shared-hosting readiness](shared-hosting-readiness.md).

An experimental release may truthfully show **uncalibrated** Judges. It may not advertise validated Judge accuracy. These are different claims and the distinction is a release requirement, not a presentation preference.

## Release gates

| #   | Gate                                                                               | Status                         | Evidence                                                                                                                                                                                        |
| --- | ---------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Owner-approved license, copyright attribution and distribution rights              | **Partially met**              | MIT `LICENSE` added, copyright "2026 Moinuddeen Hussain" as directed by the owner. Written confirmation that all included material is the owner's to distribute is **still outstanding**.       |
| 2   | No known secrets or unauthorized private material in source or reachable history   | **Met, with disclosed limits** | See [private material review](#private-material-review).                                                                                                                                        |
| 3   | A fresh extracted artifact installs and starts using its own documented files      | **Met**                        | Recorded in [verification.md](verification.md#release-candidate-packaging).                                                                                                                     |
| 4   | A no-key synthetic demo completes, and results survive restart                     | **Met**                        | Recorded in [verification.md](verification.md#synthetic-no-key-demo).                                                                                                                           |
| 5   | Each advertised mode has verified setup and failure behaviour                      | **Partially met**              | Black-box and the demo verified locally. White-box scanning needs Docker and a prepared database; it is labelled _Supported, needs setup_ and reports **Not tested** with guidance when absent. |
| 6   | Case completeness, repeat freshness, resume, cost uncertainty and audit integrity  | **Met**                        | Full suite result in [verification.md](verification.md#regression-suite).                                                                                                                       |
| 7   | UI, history and export regressions fixed and browser-verified                      | **Partially met**              | Bounded PDF export fixed and tested (T-046). Browser navigation checks recorded in [verification.md](verification.md).                                                                          |
| 8   | Pacing passes 50 of 50 bounded parallel repetitions                                | **Not tested**                 | No pacing stress harness exists in this lineage. See [the pacing note](#what-this-candidate-does-not-establish).                                                                                |
| 9   | Every advertised operating system has actual qualification evidence                | **Not met**                    | Windows 11 only. Linux and macOS are **not qualified**; support claims are narrowed accordingly in the README.                                                                                  |
| 10  | Documentation, templates, changelog, manifest, hashes and rollback instructions    | **Met**                        | This file, [CHANGELOG.md](../CHANGELOG.md), [the release checklist](release-checklist.md) and the recorded manifest.                                                                            |
| 11  | Human labels and live provider validation reported exactly as completed or blocked | **Met (reported as blocked)**  | No human labels and no live provider smoke test were obtained for this candidate. Both are reported as outstanding, not as done.                                                                |
| 12  | Publication is a separate, explicitly authorized action                            | **Pending**                    | Nothing was pushed, published or made visible by this work.                                                                                                                                     |

## What this candidate does not establish

**Judge accuracy is uncalibrated.** No representative human labels were collected. Agreement, false acceptance and false rejection rates are therefore unknown, and no confidence interval is reported. The mechanics for calibration exist; the human evidence does not. See [judge-validation.md](judge-validation.md).

**Pacing stress is untested in this lineage.** A separate local working tree contains a clock seam, fake-clock pacing tests and a bounded parallel stress harness that recorded 50 of 50 repetitions. **That work is not present in this repository**, so this candidate cannot claim it. The concurrency tests in `tests/test_concurrency.py` and the real-time benchmark in `tests/test_speed_cache.py` do pass here, and they are a narrower claim than parallel pacing stress.

**Linux and macOS are unqualified.** `start.sh` is checked in and reviewed, but was not executed on either platform for this candidate. The PDF report also prefers a Windows font path and silently falls back to default fonts elsewhere; the fallback is untested on those platforms.

**No live provider call was made.** Every test uses mocked providers and synthetic fixtures. Authentication, quota and rate-limit handling are covered by mocks only. Real provider behaviour, real billing and real model availability remain unverified.

**Optional classifiers stay disabled.** HHEM and Qwen classifiers require approved model weights that were not installed. They remain disabled and clearly unverified rather than silently absent.

**Pattern scanning cannot prove absence.** The secret review below is a pattern scan over reachable commits. It is evidence of nothing found, not proof that nothing exists.

## Private material review

Reviewed on 2026-11-09 against the candidate tree and all reachable Git history.

| Finding                                                                                                             | Type                      | Disposition                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No `.env`, key, certificate or credential file in any reachable commit                                              | Clean                     | Verified by scanning every added path across all reachable commits.                                                                                                                                                     |
| No provider-key-shaped string in any reachable commit                                                               | Clean                     | Patterns covered Google, Anthropic, OpenAI-style, GitHub, Slack and AWS keys, and PEM private-key headers.                                                                                                              |
| `tests/test_export_redaction.py`, `tests/test_judge_calibration.py`                                                 | Synthetic fixtures        | Credential-shaped literals exist **by design**: the tests assert these values are redacted out of exports and audit records. They sit beside a fictional phone number, `example.com` and documentation UUIDs. Retained. |
| A named third-party company appears in UI labels, auto-detection logic, API route names and case-pack filenames     | **Owner decision needed** | The case content itself is authored synthetic prompts using synthetic identifiers; no customer transcript or personal data is present. The _naming_ is nevertheless published. See below.                               |
| An absolute workstation path into a separate local project in `docs/api-keys.md`                                    | Fixed                     | Replaced with a portable placeholder and generalized guidance.                                                                                                                                                          |
| A quality badge pointing at an unrelated repository and branch in `README.md`                                       | Fixed                     | Removed; the README no longer claims any CI state.                                                                                                                                                                      |
| `PROGRESS.md` and `HANDOFF.md` contain workstation paths, internal ticket identifiers and another repository's name | Excluded from the archive | Both are deliberately outside the source archive manifest, and the public README no longer links them. They remain tracked in Git history.                                                                              |
| Root `*-cases.json` exports at the repository root                                                                  | Excluded from the archive | Unreferenced by any code or document; left out of the release manifest rather than shipped.                                                                                                                             |

## Owner decisions still required

1. **Distribution rights.** Confirm in writing that every included file is yours to publish under MIT, and that no employer-owned or third-party material is embedded.
2. **The named third-party company.** Decide whether to keep, rename or remove the published references. Renaming the API routes and the auto-detection string would change behaviour for existing saved Runs and for detecting that bot, so this is a product decision, not a cleanup. The repository is already public, so the references are already visible.
3. **Security reporting route.** [SECURITY.md](../SECURITY.md) must name a route you actually monitor. Nothing here invents an address or asserts that GitHub private reporting is enabled.
4. **Human calibration labels.** Two independent reviewers are needed before any Judge accuracy claim. Until then, Results, Governance and exports must keep showing the uncalibrated state.
5. **Publication.** Tagging, releasing or announcing anything is a separate authorized step.
