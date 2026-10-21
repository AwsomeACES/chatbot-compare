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

The short default suite has only one authored scenario in several categories. It is useful for screening and descriptive comparisons, but deliberately does **not** qualify for an inferential winner. Add reviewed, distinct scenarios through the existing `scenario_sets` / `scenario_file` protocol mechanism when a broader comparison is needed. Merely renaming or duplicating a prompt does not make it independent. The Studio does not automatically prove that authored scenarios are independent or representative.

Intervals are approximate and conditional on the chosen suite and judges. They do not account for every source of model bias, shifting provider versions or untested real-world scenarios. Policy values and seed are recorded with the run. Older stored reports are not migrated in bulk; explicit resume/recalculation uses the current analysis implementation and reports its method.

The methodological motivation for choosing a test that matches the experimental unit is discussed in [Dror et al., ACL 2018](https://aclanthology.org/P18-1128/). The concrete thresholds and bootstrap policy here are Studio engineering choices, not thresholds endorsed by that paper.

## Source findings

Generic secret-pattern matches on a narrowly recognized Python model-name assignment remain available for review. They are not labeled confirmed exposed keys and are not silently passed. Provider-specific credential rules and key-shaped literals still alert. Retained scanner metadata is redacted; matched secrets are not copied into the report.

OSV advisories with unresolved or placeholder versions such as `0.0.0` remain unverified. The report requests a lockfile or resolved inventory. Exact scanner-reported versions can support an advisory finding, but source scanning alone does not establish which version is deployed. Mixed reports retain both exact-version findings and unresolved candidates.

## Audit protections

Review, retention, canary-log attachment and judge changes check the existing assurance audit and findings seal before making changes. Corrupt records remain inspectable and explicitly deletable; recovery and automatic expiry do not silently re-seal them. Because automatic expiry leaves corrupt records untouched, the owner must explicitly delete their private data.

Open review items prevent the assurance combiner from displaying **Ready to launch**. Critical findings still block release. Local hashes detect changes against the stored anchor, not an attacker replacing the entire database and backups.

## Remaining work before shared enterprise deployment

- Independent human-labeled validation of judge quality and false-positive rates.
- Authentication, role-based access, tenant isolation and deployment-specific network controls for shared hosting.
- Locked dependency sets and native macOS/Linux startup and scanner qualification.
- More representative, reviewed scenario sets and wider accessibility testing.
- Stronger external audit anchoring and reproducible scanner/model revision management.

These are separate work items. This release does not claim to complete them. See [tasks.md](tasks.md) for the tracked implementation gaps.
