"""Adapter around the existing black-box engine; no duplicate scoring logic."""

import asyncio

from .. import database as db
from ..blackbox.runner import ACTIVE, scored
from ..blackbox.schema import Settings
from .models import Evidence, Finding, missing
from .privacy import safe


def findings_from_run(run: dict) -> list[Finding]:
    findings = []
    for case in run["cases"]:
        if case.get("derived"):
            continue
        for slot, result in enumerate(case["results"]):
            if not scored(result):
                findings.append(
                    missing("black", slot, case["category"], case["id"], result["reason"])
                )
                continue
            evidence = [
                Evidence(
                    kind="transcript",
                    excerpt=str(safe(turn.get("output", "")))[:4000],
                    source_id=case["id"],
                )
                for turn in result.get("transcript", [])
                if turn.get("output")
            ]
            if not evidence:
                findings.append(
                    missing(
                        "black",
                        slot,
                        case["category"],
                        case["id"],
                        "No recorded bot answer supports this score.",
                    )
                )
                continue
            evidence = [
                Evidence(kind="transcript", excerpt=str(safe(q))[:4000], source_id=case["id"])
                for q in result.get("evidence", [])
                if isinstance(q, str)
            ] + evidence
            findings.append(
                Finding(
                    mode="black",
                    bot=slot,
                    category=case["category"],
                    test_id=case["id"],
                    verdict="pass" if result["status"] == "passed" else "fail",
                    score=result["score"],
                    severity="Pass" if result["status"] == "passed" else "High",
                    confidence="Low" if result.get("estimated", True) else "Medium",
                    evidence=evidence,
                    checked=case["name"],
                    explanation=str(safe(result["reason"])),
                    consequence="Users may receive unsupported, unfair, unsafe or unhelpful answers on this scenario.",
                    fix="Correct the behavior described in the judge's reason and rerun this scenario.",
                    details={
                        "source_run": run["id"],
                        "judges": [
                            {"model": j["model"], "score": j.get("score")}
                            for j in result.get("judges", [])
                        ],
                        "estimated": result.get("estimated", False),
                        "bias_subtype": case.get("bias_subtype"),
                        "evidence_quotes": safe(result.get("evidence", [])),
                    },
                )
            )
    return findings


class BlackEngine:
    def __init__(self, config: Settings, on_start, existing_id: str = "", on_progress=None):
        self.config, self.on_start, self.existing_id = config, on_start, existing_id
        self.on_progress = on_progress

    def required_inputs(self) -> dict[str, list[str]]:
        return {"conversation": ["chat URL or API", "judge"]}

    def plan(self, inputs: dict) -> list[dict]:
        from ..blackbox.studio_engine import cases

        return [
            {"target": t.name, "bot": i, "test": c["id"], "category": c["category"]}
            for i, t in enumerate(self.config.targets)
            for c in cases(self.config)
            if not c.get("derived")
        ]

    async def run(self, plan: list[dict]) -> list[Finding]:
        import uuid

        from ..blackbox_app import resume_run, start

        if self.existing_id:
            ident = self.existing_id
            previous = db.get("blackbox", ident)
            if (
                previous
                and any(
                    r["status"] == "not_tested" for c in previous["cases"] for r in c["results"]
                )
                and ident not in ACTIVE
            ):
                await resume_run(uuid.UUID(ident), self.config)
        else:
            ident = (await start(self.config))["id"]
        self.on_start(ident)
        previous_progress = None
        while True:
            run = await asyncio.to_thread(db.get, "blackbox", ident)
            if not run:
                raise ValueError("Black-box checkpoint missing.")
            progress = (
                sum(scored(r) for c in run["cases"] for r in c["results"]),
                sum(c.get("completed", False) for c in run["cases"]),
                run["status"],
            )
            if progress != previous_progress and self.on_progress:
                self.on_progress(findings_from_run(run))
                previous_progress = progress
            if run["status"] not in ("running", "queued"):
                return findings_from_run(run)
            await asyncio.sleep(1)
