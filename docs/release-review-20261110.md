# Release review — 10 November 2026

This branch update contains the latest reviewed release-candidate changes. It is not a statement that the release gates are complete.

## Confirmed open defects

| Priority | Defect                                                                                                                                                                                   | Expected correction                                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| High     | The current dashboard has no working no-key demo setup flow. Its active assurance handler submits the normal simple-mode configuration without demo Cases or explicit Judge disablement. | Add a tested demo action using the eight existing deterministic Cases, no provider calls and persistent synthetic-data disclosure. Keep normal Judge validation. |
| High     | `scripts/release_manifest.py --artifact X --output X` overwrites the ZIP with Markdown and exits successfully.                                                                           | Reject identical/aliased paths and preserve existing artifacts/outputs with regression tests.                                                                    |
| Medium   | Git state `unavailable` is treated as a clean working tree in the release manifest.                                                                                                      | Use explicit clean/dirty/unknown states and distinguish inspection-time state from verified build provenance.                                                    |
| Medium   | Content digest concatenates member names and contents without framing. Member `a` containing `bc` and member `ab` containing `c` yield the same digest.                                  | Version an unambiguous content-manifest encoding. Full ZIP SHA-256 is unaffected by this defect.                                                                 |
| Medium   | The extracted release has four broken Rules links to excluded HANDOFF/PROGRESS documents.                                                                                                | Validate all shipped document links and supply portable public guidance without exporting private working history.                                               |

The audit also found formatting failures in PRD, DECISIONS, HANDOFF and PROGRESS. This branch integration applies the pinned formatter. It does not disable the formatting gate or claim the five functional defects above are fixed.

## Verification boundaries

The source audit ran the Windows Python suite with working localhost sockets: **817 passed, 1 skipped**, plus one Starlette deprecation warning. It also passed 23 JavaScript navigation tests, 16-file syntax checking, Ruff, pip consistency, the working-checkout docs checker and both current/legacy synthetic browser checks. The archive documentation probe failed as described above. A separate browser probe intercepted the malformed demo setup before dispatch, so it made no bot or provider calls.

These are source-audit results, not remote CI evidence. See the latest PROGRESS entry for checks on the integrated branch. GitHub Actions must be evaluated for the newly pushed commit, not by rerunning an obsolete failed commit.

Human Judge validation, parallel pacing qualification in this lineage, native Linux/macOS and Docker/scanner qualification remain incomplete. Distribution/security-reporting decisions remain recorded in the release ledger. The explicit branch-push request does not establish any of those technical results or authorize a release announcement. No Gemini credential is needed to fix the five defects listed here.
