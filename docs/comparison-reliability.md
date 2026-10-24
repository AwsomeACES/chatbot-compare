# Reliable comparisons and evidence review

This release strengthens evaluation decisions. It remains a local, single-user tool, not a certified production assurance service.

## Reading a comparison

The Results screen and PDF show the same saved decision. Expand **Comparison evidence and review checks** to see paired scenario counts, score differences, confidence intervals, and reasons that prevent a decision.

- Scores and measured coverage remain separate. Missing evidence contributes zero only to the conservative index; it is not a measured bad answer.
- Each repeat is averaged within its authored scenario. Repeating one scenario many times does not create independent coverage.
- Categories are fixed strata. The bootstrap resamples paired scenario means within each category, applies the saved category weights, and adjusts intervals across every bot pair (one pair for two bots, six for four).
- A winner must beat every other bot beyond the saved tie margin, with complete comparable panels and no unresolved evidence-review flags. Running, stopped, incomplete, or insufficiently sampled comparisons have no winner.
- Category leaders are descriptive scores, not separate statistical significance claims. They use the saved run's tie margin; changing today's settings cannot change that margin.
- **Meets configured checks** means completed evidence, no open review items, and every category meeting the configured threshold. It does not certify that a bot is safe to deploy.

## Suite size and editable policy

New runs save the `comparison` section of [settings.json](../app/studio/settings.json). Defaults are 2,000 resamples, a 95% family-wise confidence target, at least ten distinct paired scenarios overall and at least two per selected category. The practical tie margin is two score points, and the review threshold is 80 per category.

The short default suite has only one authored scenario in several categories. It is useful for screening and descriptive comparisons, but deliberately does **not** qualify for an inferential winner.

The **Extended reviewable suite** is the selectable alternative: ten distinct authored scenarios for each of nine Categories, with Bias keeping its nine subtypes from `bias-v1.json`. Choose it under **Scenario suite** on the Evaluate screen. Selecting it appends `+extended-v1` to the saved `protocol_version`, so every Run records which suite produced it and older reports stay readable on their own terms. The default stays the light screening suite.

The extended suite includes multi-turn, ambiguous, benign and adversarial scenarios, and supplies reference facts for the factual Category that state their own scope. Every scenario is marked `authored`: none has been reviewed by a second person, and the suite says so in its own limitations and in the Evaluate screen. A larger suite reduces the chance of missing a known failure mode; it does not establish that a bot is safe, and it does not make the Studio's coverage representative of real traffic.

Merely renaming or duplicating a prompt does not make a scenario independent. Repeats of one scenario are a separate multiplier and are never counted as distinct scenarios anywhere — in planning, in the comparison's paired means, in calibration sufficiency or in the suite's own coverage block. The Studio does not automatically prove that authored scenarios are independent or representative.

Intervals are approximate and conditional on the chosen suite and judges. They do not account for every source of model bias, shifting provider versions or untested real-world scenarios. Policy values and seed are recorded with the run. Older stored reports are not migrated in bulk; explicit resume/recalculation uses the current analysis implementation and reports its method.

The methodological motivation for choosing a test that matches the experimental unit is discussed in [Dror et al., ACL 2018](https://aclanthology.org/P18-1128/). The concrete thresholds and bootstrap policy here are Studio engineering choices, not thresholds endorsed by that paper.

## Source findings

Generic secret-pattern matches on a narrowly recognized Python model-name assignment remain available for review. They are not labeled confirmed exposed keys and are not silently passed. Provider-specific credential rules and key-shaped literals still alert. Retained scanner metadata is redacted; matched secrets are not copied into the report.

OSV advisories with unresolved or placeholder versions such as `0.0.0` remain unverified. The report requests a lockfile or resolved inventory. Exact scanner-reported versions can support an advisory finding, but source scanning alone does not establish which version is deployed. Mixed reports retain both exact-version findings and unresolved candidates.

## Audit protections

Review, retention, canary-log attachment and judge changes check the existing assurance audit and findings seal before making changes. Corrupt records remain inspectable and explicitly deletable; recovery and automatic expiry do not silently re-seal them. Because automatic expiry leaves corrupt records untouched, the owner must explicitly delete their private data.

Open review items prevent the assurance combiner from displaying **Ready to launch**. Critical findings still block release. Local hashes detect changes against the stored anchor, not an attacker replacing the entire database and backups.

## Judge calibration against human labels

Results can now compare a selected judge with labels you enter yourself on saved conversations (see [bias-governance.md](bias-governance.md#judge-calibration-with-human-labels)). The workflow measures the judge's own pass/fail decision at the 80 boundary on the same retained evidence, reports agreement with denominators, a confusion matrix, false acceptance/rejection rates and each disagreement, and warns when calibration is missing, stale, incomplete, too small or below the configured agreement. Defaults (80% agreement, 100% comparable coverage, 10 distinct scenarios, 2 human-pass and 2 human-fail scenarios) are engineering choices in `settings.json`, not scientific sufficiency standards.

A seeded sample is spread across Categories by default, and can optionally alternate the saved Judge's own passes and failures so a nearly-all-passing Run still yields measurable false acceptance; that option changes the sampled base rate and records a note saying so. Freezing a version can reserve a held-out subset, split by scenario so repeats never straddle the two folds, for use after prompts are adjusted in response to disagreements. Each fold reports its own denominators and the headline stays the whole frozen sample.

No representative human-labeled validation has been collected in this repository, so every Judge currently reports **uncalibrated**. [judge-validation.md](judge-validation.md) is the owner's procedure for running a genuine exercise and for recording its reviewer limitations. Agreement figures produced from fabricated or AI-generated labels are not evidence of Judge accuracy and must not be reported as validation results.

This capability does not complete independent validation. A small owner-labeled sample is conditional on that sample and rubric; it is not certification, not universal judge accuracy, and gives no confidence interval. A changed model, endpoint, prompt template, rubric, policy or validation code makes earlier calibration inapplicable. If you edit the rubric after inspecting disagreements, validate on a new held-out sample.

## Remaining work before shared enterprise deployment

- Independent human-labeled validation of judge quality and false-positive rates. The calibration workflow below exists, but representative, reviewed labels and recorded validation results do not.
- Authentication, role-based access, tenant isolation and deployment-specific network controls for shared hosting.
- Locked dependency sets and native macOS/Linux startup and scanner qualification.
- More representative, reviewed scenario sets and wider accessibility testing.
- Stronger external audit anchoring and reproducible scanner/model revision management.

These are separate work items. This release does not claim to complete them. See [tasks.md](tasks.md) for the tracked implementation gaps.
