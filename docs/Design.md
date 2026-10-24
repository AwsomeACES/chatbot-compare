# AI Agent Studio — Interface design

Purpose: describe the current interface and distinguish proposed additions from shipped screens.
Owner: AI Agent Studio maintainers; named design reviewer: TODO: confirm.
Last updated: 2026-10-17.

## Contents

- [Principles](#principles)
- [Screen inventory](#screen-inventory)
- [Components](#components)
- [Visual system](#visual-system)
- [Content and states](#content-and-states)
- [Accessibility and responsive behavior](#accessibility-and-responsive-behavior)
- [Design gaps](#design-gaps)

## Principles

Use plain English for instructions and keep technical names such as Black-box testing, Gray-box testing, White-box testing and Governance. A Finding is a saved check result with evidence; an Engine performs checks; a Judge evaluates answers; a Run is one assessment; a Case is one scenario; a Category groups related Cases. An Assurance badge describes selected evidence modes. Full product definitions and scope are in [PRD](PRD.md).

Keep the first screen short, optional details collapsed, evidence reachable, and uncertainty visible. “Not tested” must never look like a pass. Keep measured quality, missing-evidence index and coverage distinct. Calm design means stable panels, concise explanations and no celebratory “safe” claim based only on scanner completion. Use original-language transcripts as evidence even though navigation and help are English.

The active shell is [simple.html](../app/blackbox_static/simple.html), not the retained legacy `index.html`. Shared navigation is Evaluate / Results / Governance. Component IDs refer to [Architecture](Architecture.md#components). The wireframes below are simplified text layouts, not new screens implemented by this documentation.

## Screen inventory

### Setup — implemented within Evaluate

C01 interface, C02 API, C03 intake/planner, C08 judges.

```text
AI Agent Studio        Evaluate | Results | Governance
Previous tests [Choose a previous test v] [Refresh history]

How well does your bot help people?
1 Add your bots
  [x] Black-box testing [ ] White-box testing [ ] Gray-box testing
  Chatbot 1: [Name] [Chat link or API endpoint]
  > Connection settings (optional)
  Source/private inputs appear for selected modes
  [+ Add another bot]                       (up to four)
2 Choose an AI judge
  Saved judge summary
  > Change model or API key
    [ ] Judge choices / model / password field
    > Local backup
3 Start your test
  Repeat each test [3] times
  > View tests and customize repeats
  > Advanced settings — optional
  [ ] Ownership/permission
  [ ] Test messages and AI review consent
  [Start test] [Update judges for this run]
```

White-only selection hides irrelevant chat/judge settings; source upload does not start the uploaded bot. Private Gray inputs have a separate cloud opt-in. The fields are described in [Architecture contracts](Architecture.md#contracts). A universal color-coded readiness checklist is Planned.

### Live progress — implemented in Results

C01, C04–C06 engines, C09 scheduling/cache, C12 costs.

```text
Selected Run [name / status]  [Refresh] [Resume missing cases] [Stop run]
Overview
[progress bar]  Current stage / processed count
Judge status and any switch/unavailable reason
Partial scores + coverage
> Progress and timings by category
  Bot | Category | Planned | Processed | Timing
```

Black progress supports event streaming (the server sends changes as they happen) and refresh. Assessment results refresh through their API. Counts can include explicit missing Findings and derived Bias records. Do not describe processed count as number of successful judgments. Saving an old selection must not replace a newer selection when a slow request finishes.

### Results — implemented

C01, C07 combiner, C08 explanation, C10 storage, C13 exports.

```text
Your evaluation results
Black-box testing | Gray-box testing | White-box testing | Summary
[Download report] [Stop test / Resume test] > More actions

[Original/combined verdict + reason]
checks recorded | passed | need attention | not tested
[Optional AI source review + provenance]
> Compare all categories
  Category | selected modes | Combined interpretation | Confidence
What needs attention?
  > Finding title / status / severity / Overridden
    What we checked / What we found / Why it matters / How to fix it
    Source or transcript evidence
    [Review this finding]
```

The internal Combined tab is visibly labeled **Summary**. Basic, Standard, Full or Custom is an Assurance badge value, often shown as text, not a certification seal. Black results contain detailed scores and Cases; Gray/White cards contain source/trace or behavioral Findings. An optional AI source review retains the original scanner summary and is not a human override.

### Compare — implemented as a Black Results section

C01, C04 comparison summary, C08 judges. There is no separate Compare navigation page.

```text
Comparison summary / Winner: [bot name]
Confidence note / incomplete evidence / tie explanation
Bot A [score bar]    Bot B [score bar]    ... up to four
Category | Bot A score+coverage | Bot B score+coverage | Result
Bias     | one aggregate bar   | one aggregate bar   | Tie/name
> Bias sub-tests and paired evidence
  Type | score/status/severity | one-line reason
  [Pair A prompt + excerpt] [Pair B prompt + excerpt]
```

The Category Result column already displays a winner name, Tie, Scored or Incomplete evidence. Its tie comparison currently reads current page settings; verifying historical protocol tie-margin consistency is a follow-up. Overall winner eligibility is calculated on the backend. Separate head-to-head legacy comparison must not be presented as the simple protocol's method.

### Cost — implemented as Tokens and cost in Results

C01, C12 metering and C13 exports. USD means US dollars.

```text
Tokens and cost
Bot cost [amount/Unknown]         Judge cost [amount/Unknown]
Bot or Judge model | Input | Output | Tokens bar | USD cost | Cost bar
Known amount and unknown-call explanation, where available
Measurement caveat: visible interface / estimated tokens
```

Unknown cost has text in place of a zero-length dollar bar. Local zero API charge is labeled; hardware cost may remain unmetered. Existing bars and tables carry the values; no pie chart is needed. Detailed price overrides remain available through retained advanced/legacy controls rather than a new simple-screen Settings page.

### Governance — implemented shared view

C01, C10 storage, C11 audit/review, C13 export.

```text
Governance and audit
Run integrity
Accounted for | Audit chain | Judge agreement | Human overrides
[Repeat/reproduce] [Export] [Privacy controls]
> Bots and judges used
  Bot card / Local or Cloud judge card / revision / endpoint
> Advanced audit details
  Run ID / test suite / configuration hash
  > Judge prompts, errors, retries and switches
> Privacy and data retention
> Framework mapping (informational)
```

Assessment Governance has a compact variant: assurance/release summary, audit state, collapsed “Bots and AI judges” metadata, review count, upload retention and actions. These variants share navigation but are not identical rich card layouts. Hashes are fingerprints of saved values; they detect specific changes, not legal authenticity.

### Judge calibration — implemented across Evaluate, Results and Governance

C01, C02, C08, C11. A persistent status line under the selected judge on Evaluate and a Human alignment section on Governance always state one of: not calibrated, calibration out of date, incomplete, sample too small, not aligned, or meets configured criteria, using words as well as color. Results has a collapsed **Calibrate a judge on saved conversations** panel: pick conversations or a seeded sample, label them (pass/fail or score, optional rationale, original judge output hidden), freeze a version, evaluate, then inspect counts, confusion matrix, error rates with denominators, sufficiency checks and every disagreement with the judge's reason and the retained conversation. It is diagnostic only and separate from judge agreement between models.

### Human review queue — implemented across Results and Governance

C01, C07 review queue, C11 review routes. A dedicated queue page is Planned.

```text
Governance: [count] findings/items needing review
Results / Summary:
  Finding (Critical or low confidence)
  evidence + reason + proposed fix
  [Review this finding]
    Write reason [browser prompt]
    Mark as false positive? [confirm / cancel keeps finding]
  Overridden / review note / preserved original
```

The current assurance flow uses browser prompt/confirm dialogs. A false positive means a tool alert that does not represent the claimed issue. Canceling the false-positive confirmation still records the written review while keeping its score. A richer accessible review form is Planned; do not claim it exists today.

### Settings — implemented as collapsed controls, not a separate page

C01, C03, C08, C12.

```text
Evaluate
  > Connection settings (optional)
  > Change model or API key
  > Advanced settings — optional
      Reference facts / Safety rules / Scope
      Private inputs and retention
      [ ] Allow selected cloud judges to review private inputs
Results
  [Load this run’s settings]    (explicit, never automatic)
Governance
  Retention / credentials for reproduction when requested
```

Maintain editable configuration files for operators as listed in [Architecture](Architecture.md#files-and-deployment). Do not expose every implementation option to first-time users. A standalone settings page is not required to deliver the existing workflow.

## Components

| Component             | Current behavior / gap                                                                                                                                                |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Score bars            | Horizontal bars with numeric score, scored/planned coverage and measured quality.                                                                                     |
| Category × mode table | Collapsed “Compare all categories”; each selected mode plus Combined interpretation and confidence.                                                                   |
| Assurance badge       | Basic / Standard / Full / Custom, describing mode selection; missing evidence is separately disclosed.                                                                |
| Verdict banner        | Release recommendation or Black comparison summary with qualification. Optional source review labels the original scanner summary.                                    |
| Finding card          | Four required explanation headings, severity/confidence, escaped excerpts, file/line where available. Escaping displays model text literally instead of running HTML. |
| Transcript viewer     | Expanded on demand; Bias evidence uses paired grid cards that stack on narrow screens.                                                                                |
| Low confidence badge  | Implemented for Black Categories below half scored coverage; not a calibrated probability.                                                                            |
| Estimated indicator   | Token/cost provenance and caveat text exist. A consistent Estimated badge across all report types is Planned.                                                         |
| Overridden indicator  | Assurance summary adds “Overridden”; Black evidence uses “Overridden — reason logged”.                                                                                |
| Not tested indicator  | Explicit status/reason; no green pass styling.                                                                                                                        |
| Glossary              | Some combined labels use a native `title` tooltip. A full keyboard-accessible hover/focus glossary is Planned.                                                        |
| Hinglish toggle       | Not implemented in the current English shell; previously removed. Planned only if explicitly reauthorized; do not reintroduce it through documentation.               |

## Visual system

Values come from [simple.css](../app/blackbox_static/simple.css). CSS is the stylesheet that controls layout and appearance. The legacy [style.css](../app/blackbox_static/style.css) uses a different Arial-based theme and is not the active shell's design system.

| Meaning                               | Current CSS value     |
| ------------------------------------- | --------------------- |
| Body text / page background           | `#202940` / `#f6f7fb` |
| Accent / active navigation background | `#5146ce` / `#efedff` |
| Borders / muted text                  | `#e1e5ef` / `#657089` |
| Positive `.good`                      | `#087058`             |
| Failure `.bad`                        | `#a42232`             |
| Unknown/warning `.unknown`            | `#825d1c`             |
| Warning panel background / border     | `#fff8e8` / `#eadbb6` |
| Generic pill background / text        | `#f0edfc` / `#665390` |
| Score bar track / fill                | `#efedf8` / `#8274df` |
| Keyboard focus outline                | `#a69bf3`, 3px        |

Not tested has no dedicated semantic color token today; it relies on explicit text, generic pills and warning/muted styling. Do not claim a complete four-color semantic system already exists. Standardizing these states is Planned.

Typography is `16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. Main content max width is 1200px, with 24px horizontal padding and 48px bottom padding. Sections use 24px padding and 13px corners; common gaps are 8, 12, 16 and 20px, rather than a formal token scale. The main heading uses `clamp(1.7rem, 3vw, 2.15rem)`. Icons are text/CSS and native controls; the decorative brand “A” is hidden from assistive reading. No installed universal icon system is claimed.

Charts use horizontal score, token and cost bars with tables. A native progress element shows processing. The current shell is light-only: no dark theme, preference switch or `prefers-color-scheme` implementation was found. Dark mode is Planned, low priority.

## Content and states

Use short sentences, state the evidence, and distinguish source observation from behavioral proof. The following are exact current labels in the primary interface. Backend exception details and runtime model text are dynamic; a complete unified error-message catalogue does not exist and is Planned. Keep safe backend reasons visible without exposing credentials.

| State                    | Exact current text                                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Finding verdicts         | `Passed`, `Needs attention`, `Not tested`, `Declaration only`                                                                              |
| Combined mode cells      | `Pass`, `Fail`, `Not tested`                                                                                                               |
| Combined interpretations | `Defended`, `Confirmed risk`, `Control exists but isn't working`, `Passed, code not checked`, `Not tested`                                 |
| Release summary          | `Ready to launch`, `Fix before launch`, `Do not launch`                                                                                    |
| Assurance                | `Basic`, `Standard`, `Full`, `Custom`                                                                                                      |
| Black summary            | `Evaluation summary`, `Comparison summary`, `Winner: {name}`                                                                               |
| Category result          | `Scored`, `Tie`, `Incomplete evidence`, or the bot name                                                                                    |
| Missing quality          | `Not measured`, `Not tested yet`, `Not tested in this saved run`                                                                           |
| Missing Case score       | `Not tested (index contribution 0)`                                                                                                        |
| Review labels            | `Low confidence`, `Needs human review`, `Overridden`, `Overridden — reason logged`                                                         |
| Costs                    | `Unknown`, `<$0.0001`, `$0 (local)`, `$0 (no bot API calls)`                                                                               |
| Audit chain              | `Intact`, `Changed`, `Unavailable`; assessment variant uses `Needs review`                                                                 |
| Run selection            | `No run selected`, `Choose a previous test`, `Choose a test above.`                                                                        |
| Empty Results            | `Choose a test to see its results` / `Select a previous test above, or start a new one.`                                                   |
| Empty Governance         | `Choose a saved evaluation to inspect its audit.`                                                                                          |
| Loading                  | `Loading your saved judge…`, `Loading selected test…`, `Loading selected evaluation…`, `Loading audit evidence…`                           |
| Source processing        | `Test in progress`; `Source scan: {processed}/{checks} checks processed. A completed scan can still lack enough evidence to pass a check.` |
| Deleted/expired report   | `This test is no longer available. Choose another test or start a new one.`                                                                |
| Missing Finding evidence | `No supporting evidence was obtained.`                                                                                                     |
| Missing bot response     | `No response`                                                                                                                              |
| Fallback unavailable     | `Ollama is unavailable or has no installed models. No automatic local fallback can run yet.`                                               |
| Judge failure            | `Unavailable: {reason}`                                                                                                                    |
| Request fallback errors  | `Upload failed`, `Request failed`; otherwise a safe API error detail.                                                                      |
| Resume notice            | `Resuming missing cases. Completed scores and costs remain recorded.`                                                                      |
| Completed Governance     | `Evidence loaded. Review any missing tests or warnings before using the result.`                                                           |

Run statuses are stored as machine strings (such as `queued`, `running`, `completed`, `stopped`, `interrupted`, `timed_out`); some views display them directly or replace underscores with spaces. Centralizing their presentation is Planned. These labels are not interchangeable with Finding verdicts. An `exists` Finding is labelled `Declaration only` in every mode, because neither a source declaration nor an operator declaration shows that the control works; the per-check guidance states what that check could see. The finding review is an in-page `dialog` with a labelled reason field, radio choices, a visible validation message and Escape to cancel, rather than browser `prompt`/`confirm` dialogs, and the category matrix shows each reason as focusable text instead of a hover-only tooltip ([tests/test_review_accessibility.py](../tests/test_review_accessibility.py)).

Example Finding copy, proposed editorial wording rather than a fabricated executed result:

> **What we checked:** Whether a session can be accessed only by its owner.
> **What we found:** The supplied handler accepts a session ID, but this source excerpt does not establish an owner check.
> **Why it matters:** Someone who obtains another session ID might access another conversation; deployment controls were not tested.
> **How to fix it:** Bind sessions to authenticated users and add an access-control test.

Example final-verdict copy using the existing label:

> **Fix before launch.** Some checks need more evidence. Review the listed findings and provide the missing configuration before relying on this report.

Do not change a release summary silently when an AI explanation disputes a raw alert. Preserve the alert, provenance and written review process.

## Accessibility and responsive behavior

Implemented: labeled fields, a skip-to-content link, semantic buttons/details, status live regions (screen-reader announcements), selected navigation state, keyboard focus outlines, numeric values beside bars, and responsive grids. Preserve open evidence on refresh. Shared history cancels stale fetches and clears unavailable reports instead of showing old evidence as a new selection.

At 650px or less the header wraps, navigation fills width, main/section padding shrinks and several grids become single-column; an additional 600px rule adjusts compact history controls. Tables retain an overflow wrapper for horizontal scrolling. These are actual breakpoints, not a claim that every device has been tested.

Planned: measure contrast against an agreed accessibility standard, audit keyboard order and all browser dialogs, ensure chart/table semantics are readable with assistive tools, provide glossary content on focus as well as hover, and test touch/reduced-motion/zoom behavior. Never communicate failure or uncertainty only through color. TODO: confirm the acceptance standard and representative browser/device matrix.

## Design gaps

Track changes through [tasks](tasks.md), with [Rules](Rules.md) for verification. Priorities are a unified readiness panel, consistent status/error copy, an accessible review form, and parity of optional AI explanations across exports. Dark mode and any language toggle are separate Planned work, not prerequisites for an honest result. This document does not authorize interface changes or replace the English-only preference.

## Comparison evidence and review checks

Results includes a collapsed **Comparison evidence and review checks** section. It shows the saved tie margin and minimum distinct-scenario policy, a table of bot pairs with differences and adjusted intervals, and per-bot review reasons. **Meets configured checks** is explicitly not production certification. Category leaders use the backend saved-policy decision, with a saved-margin fallback for older reports; absent policy is labeled unavailable rather than guessed from current settings. PDF exports include the same evidence and readiness checks. See [comparison reliability](comparison-reliability.md).
