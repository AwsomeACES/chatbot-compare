# Validating a Judge against your own labels

This document is the owner's procedure for turning the Calibration workflow into a real validation exercise. The code is implemented; the labels are not. Until you label a sample yourself, every Judge in this Studio is **uncalibrated**, and the Results, Governance and export screens say so.

Nothing here certifies a Judge. A completed exercise tells you how often one Judge agreed with one reviewer on one sample of one bot's saved conversations. See [comparison-reliability.md](comparison-reliability.md) and [bias-governance.md](bias-governance.md#judge-calibration-with-human-labels) for how that status is displayed.

## Contents

- [What counts as a valid exercise](#what-counts-as-a-valid-exercise)
- [Step 1 — Draw a sample](#step-1--draw-a-sample)
- [Step 2 — Label blind](#step-2--label-blind)
- [Step 3 — Freeze a version](#step-3--freeze-a-version)
- [Step 4 — Evaluate the Judge](#step-4--evaluate-the-judge)
- [Step 5 — Read the result](#step-5--read-the-result)
- [Step 6 — Review disagreements and adjudicate](#step-6--review-disagreements-and-adjudicate)
- [Step 7 — Change prompts, then use the held-out fold](#step-7--change-prompts-then-use-the-held-out-fold)
- [Recording reviewer limitations](#recording-reviewer-limitations)
- [What invalidates an exercise](#what-invalidates-an-exercise)

## What counts as a valid exercise

A calibration run is only evidence about the Judge if all of the following hold. The product checks the mechanical ones and shows a warning when they fail; the rest are your responsibility.

| Requirement                                          | Checked by the product                                                 | Your responsibility                                                      |
| ---------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Labels entered by a human, not copied from any model | Labels live only in the Calibration set and never enter a Judge prompt | Do not paste model output into a label                                   |
| Judge output hidden while labeling                   | Original scores and reasons are never copied into a set                | Do not open the original Run beside the labeling screen                  |
| Enough distinct scenarios                            | `min_distinct_scenarios`, default 10                                   | Choose a sample that is worth ten or more scenarios                      |
| Both classes present                                 | `min_human_pass_scenarios` and `min_human_fail_scenarios`, default 2   | Include failures you consider genuinely wrong, not only formatting slips |
| Every selected item labeled and judged               | `min_comparable_coverage_percent`, default 100                         | Finish the set, or remove what you cannot label                          |
| Repeats not counted as independent                   | Repeats are grouped by scenario everywhere                             | Do not add repeats to reach a sample size                                |
| Frozen evidence                                      | A frozen version is immutable and hashed                               | Do not relabel to chase a better number                                  |

Sample size: aim for **50 to 100 retained conversations**. The seeded sample defaults to 60 and is capped by `max_sample_size` (default 100) in the `judge_calibration` section of [settings.json](../app/studio/settings.json). Smaller samples are allowed and are reported as descriptive only.

## Step 1 — Draw a sample

Open **Governance → Judge calibration**, choose a finished saved test, then create a set.

- **Seeded sample** is the reproducible option. The same seed and the same saved Run always produce the same sample, so you can state how the sample was drawn.
- **Spread the sample across Categories** is on by default. It takes one conversation from each Category in turn, so a ten-Category Run cannot yield a sample that silently omits three Categories.
- **Include saved failures as well as successes** alternates the original Judge's own passes and failures inside each Category. Use it when the Run passed almost everything, because a sample of forty successes and one failure cannot measure false acceptance. It changes the sampled failure rate, so the export records a base-rate note and the false-acceptance and false-rejection figures are conditional on the sample rather than population rates. The original outcome is used only to spread the draw: it is never stored on an item or shown while labeling.
- **Checked conversations** is the explicit option when you want named Cases. State why you picked them; a hand-picked sample is a biased sample unless you say what the rule was.

Anything that cannot be labeled is listed with a reason rather than dropped: missing or error-containing transcripts, derived Bias aggregates, measured latency Cases, a retired criterion, oversized evidence, or evidence that can no longer reconstruct a Judge request. Keep that exclusion list with your write-up — it is part of the sample description.

## Step 2 — Label blind

Label each item from the transcript and the criterion alone. The set never contains the original Judge's score, verdict, reason or evidence quotes, so the screen cannot show them to you.

- Record a **verdict** (pass or fail), or a **score** from 0 to 100. A score of 80 or more is a pass: that is the same boundary the Judge is held to. A verdict and a contradicting score are rejected.
- Write a short **rationale**. You will need it in Step 6, and a disagreement without a reason is not reviewable.
- Changing a label creates a new revision and requires a written reason of at least ten characters. Earlier revisions are kept, so a later change never erases what you first thought.

The product cannot verify that you had not already seen the original Judge's output. The set records `prior_exposure_possible: true` for exactly this reason, and the limitation appears in every export. If you have already read the Run's Results screen in detail, prefer a different Run.

## Step 3 — Freeze a version

Freezing copies the items and their current labels into an immutable, hashed version.

Set **Hold out this percentage of scenarios** before you freeze if you intend to adjust prompts or rubrics later — see Step 7. A holdout is split by scenario, never by item, so repeats of one scenario always land in the same fold; otherwise a held-out number would partly restate work you had already reviewed. A holdout needs at least two distinct scenarios. Zero reserves nothing.

20% to 30% is a reasonable holdout. Reserving it costs you development-fold precision, so reserve it only when you expect to change the configuration.

## Step 4 — Evaluate the Judge

Choose the frozen version and start the evaluation. The Judge receives only the saved transcript and the rubric fields. Human labels are never sent. No bot is called, and the original Run's scores, winners, model-to-model agreement and costs are untouched.

- A local Judge needs no consent step. A cloud Judge requires explicit consent for that endpoint and that exact frozen payload, and the calls are metered separately under the `calibration` mode.
- If a fallback model answers some items, its results are attributed to **that** model. A fallback never inherits the requested Judge's status, and a partly-fallback evaluation is never reported as a completed evaluation of the requested Judge.
- Interrupted work resumes for the same evaluation. Items the Judge could not answer stay **Not tested** with a reason and are excluded from the agreement denominator, which is why the default requires 100% comparable coverage.

## Step 5 — Read the result

The result reports, with explicit denominators:

- **Agreement**: matching decisions over validly judged items.
- **Confusion matrix**: human pass or fail against Judge pass or fail.
- **False acceptance**: the Judge passed what you failed, over your failures.
- **False rejection**: the Judge failed what you passed, over your passes.
- **Sufficiency**: distinct scenarios, scenarios with repeats, duplicate transcripts, and per-Category labeled, judged and scenario counts.
- **State**: `incomplete`, `not_aligned`, `insufficient_sample` or `meets`.

`meets` means **meets configured calibration criteria**. It is not production certification, not a guarantee about other bots or Categories, and not a confidence interval. Write the agreement figure with its denominator and the sample description, or do not quote it.

A fold table appears when you reserved a holdout. Each fold carries its own denominators. The headline stays the whole frozen sample, because a 30% fold is not a stronger result than the sample it came from.

## Step 6 — Review disagreements and adjudicate

Every disagreement is listed with your verdict and rationale beside the Judge's verdict, score, reason and evidence quotes, plus the transcript and criterion. Work through them and classify each one:

1. **Judge error.** The evidence supports your label. This is what the exercise is measuring.
2. **Label error.** On re-reading, you were wrong. Correct the label with a written reason. This creates a revision; the original stays in the record. Re-freeze and re-evaluate, and say in your write-up how many labels you revised — a sample you corrected after seeing the Judge's answers is no longer fully blind.
3. **Ambiguous criterion.** Neither reading is wrong, because the criterion does not decide the case. Do not resolve this by relabeling. Record it, and either narrow the criterion in the protocol — which invalidates the calibration for the changed items, by design — or exclude the item and say so.
4. **Unreviewable.** You cannot judge it, for example through missing domain knowledge or a language you do not read. Remove it from the set with a reason rather than guessing, and count it in the limitations.

For an ambiguous case, write the adjudication reason next to the item in your own notes and keep it with the export. The product stores your label revisions and their reasons; it does not store a separate adjudication category, so that belongs in the write-up.

If you reserved a holdout, **review only the development fold** at this step.

## Step 7 — Change prompts, then use the held-out fold

Reviewing disagreements and then tuning the Judge prompt, rubric or model against the same items produces a number that describes the tuning, not the Judge.

The honest sequence:

1. Review disagreements in the **development** fold only.
2. Change the Judge, prompt, rubric, policy or scope.
3. Start a **new** evaluation on the **same frozen version**.
4. Read the **holdout** fold as the unreviewed result, and report both folds.

The product helps here but does not enforce it. Changing the model, endpoint, prompt template, evidence-validation semantics, evaluation settings, policy, scope or a Case criterion changes the evaluator or rubric fingerprint, so the earlier calibration is shown as **stale** with the specific reasons rather than carried forward. It cannot detect that you read the holdout disagreements anyway. Once you have reviewed a holdout fold, it is a development fold.

## Recording reviewer limitations

Put these in your write-up. None of them are defects; omitting them is.

- **One reviewer.** A single owner's labels have no inter-rater agreement, so an idiosyncratic reading cannot be distinguished from a correct one. Two reviewers over the same frozen version would give that, and this product does not provide a second-reviewer workflow.
- **Prior exposure.** State whether you had seen the Run's results before labeling.
- **Revised labels.** State how many labels you changed after Step 6, and why.
- **Scope.** Name the bot, the Run, the Categories present, the language of the transcripts, and the sample size and seed. Agreement does not transfer outside them.
- **Base rate.** If you used outcome balancing or hand-picked items, say so; false acceptance and false rejection are then conditional on the sample.
- **Domain.** Name the Categories where you were not confident.
- **Provider revision.** The returned model name is not a guaranteed immutable revision, so a silent upstream change is not detected.

## What invalidates an exercise

- Labels derived from any model's output, including this Studio's own Judge or AI explanations.
- Labeling with the original Judge's output visible.
- Relabeling to raise agreement without recording the revisions.
- Quoting an agreement figure without its denominator and sample description.
- Treating repeats, paraphrases or duplicated prompts as independent examples.
- Reporting a fold as if it were the whole sample, or the whole sample as if it were the harder fold.
- Calling any result certified, production-ready or evidence of universal Judge accuracy.

Deleting the source Run or assessment deletes the copied evidence and marks dependent calibrations invalidated. Export the evaluation first if you need to keep the record.
