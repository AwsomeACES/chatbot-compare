# Explicit capability backlog

These are open engineering tasks, not completed features. They replace vague
pending claims in the historical log. This file does not update Jira remotely.

| Task     | Scope                              | Acceptance criteria                                                                                                                                                                                                                                  |
| -------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MAINT-01 | Isolated ZIP runner                | Choose an isolation backend; enforce filesystem, network, resource and time limits; test escape attempts/cancellation. Keep host execution disabled.                                                                                                 |
| MAINT-02 | Optional evaluation engines        | In a separate environment, install and execute real DeepEval, DeepTeam, Garak, HHEM and QwenGuard adapters/models. Prove metering/cancellation and document hardware/model/license requirements. Generic adapter fixtures are insufficient.          |
| MAINT-03 | External connector/provider matrix | With explicit target access and judge sharing permission, run bounded REST, compatible-API, SSE and widget examples; record versions, authentication needs, redacted evidence and failures. Do not reuse stale website status or model availability. |
| MAINT-04 | Authored cases beyond core suites  | Replace legacy scenarios with distinct reviewed cases; record provenance, coverage rationale, expected behavior and import tests. Do not pad counts.                                                                                                 |
| MAINT-05 | Blind arena and release gates      | Specify hiding/unblinding, permissions, minimum coverage, statistical rules and regression policy; implement and test before presenting them as available.                                                                                           |

Distribution milestone: publish Ticket 89 and inspect the resulting GitHub Actions
run. Local verification and configured CI are not evidence that a hosted job ran.
