# Category checks and repeated cases

The simple screen includes 16 categories. Each now has 10 authored distinct scenarios in
`app/studio/scenarios.json`. The default is five repeats per scenario: 800 case executions
per bot. Multi-turn and paired bias cases include several messages. Repeated runs test
consistency, not new independent coverage.

Hallucination uses supplied reference facts by scenario position when available; remaining
scenarios challenge unsupported claims. Relevant and irrelevant hallucination have their
own scores, independent bars, and transcripts. References are declared ground truth, not
proof of independently verified live data.

Religion, caste, sex/gender, skin colour and accessibility each have ten paired service
scenarios. Only the attribute changes within each pair. Appropriate personalization is
allowed; different wording alone is not evidence of discrimination. Read both responses.

Historical runs retain their original cases and protocol. New checks need a new run.
The dashboard distinguishes measured quality and coverage from its configured worst-case
index, where missing evidence contributes zero. Each case still records its failure reason.
