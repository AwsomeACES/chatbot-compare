/* Read-only report details shared with the unified Results screen. */
(() => {
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const score = (value) => (value == null ? "Not measured" : `${escape(value)}%`);
  const list = (rows, empty) =>
    rows.length ? `<ul>${rows.map((row) => `<li>${row}</li>`).join("")}</ul>` : `<p>${empty}</p>`;

  window.renderEvidenceDetails = (item, result) => {
    const exact = list(
      (result.deterministic_checks || []).map(
        (check) =>
          `${escape(check.kind)}: ${escape(check.term)} — ${check.met ? "Satisfied" : "Failed"}`,
      ),
      "No exact checks recorded.",
    );
    const second = result.secondary_judge;
    return `<div class="evidence-details"><p><strong>Expected:</strong> ${escape(item.expected || "Not recorded")}</p>
      <p><strong>Case time:</strong> ${result.seconds == null ? "Not measured" : escape(result.seconds) + " seconds"}${result.estimated ? " · AI estimate" : ""}</p>
      ${result.review_reason ? `<p><strong>Evidence needs review:</strong> ${escape(result.review_reason)}</p>` : ""}
      ${result.evidence?.length ? `<p><strong>Judge evidence:</strong> ${result.evidence.map(escape).join(" | ")}</p>` : ""}
      ${result.unmatched_evidence?.length ? `<p><strong>Unverified quotes:</strong> ${result.unmatched_evidence.map(escape).join(" | ")}</p>` : ""}
      ${result.deterministic_checks?.length ? `<h4>Exact checks</h4>${exact}` : ""}
      ${second ? `<h4>Second judge</h4><p>${score(second.score)} — ${escape(second.reason)}. ${second.status === "judged" ? (second.agrees ? "Agrees with primary pass/fail" : "Disagrees with primary pass/fail") : "Not tested"}</p><p>${(second.evidence || []).map(escape).join(" | ")}</p>` : ""}
      ${
        Object.keys(item.pairs || {}).length
          ? `<h4>Pairwise evidence</h4>${list(
              Object.entries(item.pairs).map(
                ([key, pair]) =>
                  `${escape(key)}: ${escape(pair.reason)}${pair.needs_review ? " — Evidence needs review" : ""}`,
              ),
              "",
            )}`
          : ""
      }
      <details><summary>Case identity and evidence digest</summary><p>${escape(item.id)} · ${escape(item.variant_note)}</p><p>Evidence digest: ${escape(item.evidence_sha256 || "Not recorded")}</p></details></div>`;
  };

  window.renderResultAnalysis = (run) => {
    const names = Object.fromEntries(
      (run.summary?.[0]?.categories || []).map((c) => [c.id, c.name]),
    );
    window.renderCost(run);
    window.renderAdvancedResults(run, names);
    // The retained charts use the historical quality/coverage policy, not the simple index.
    document.getElementById("charts").hidden = !!run.studio;
    if (!run.studio && run.summary?.length) window.drawDashboard(run, names);
    else document.getElementById("charts").innerHTML = "";
    document.getElementById("analysis-summary").innerHTML = (run.summary || [])
      .map((summary, slot) => {
        const failures = run.cases.filter((c) => c.results[slot]?.status === "failed");
        return `<article class="metric"><h3>${escape(summary.name || run.targets[slot]?.name)}</h3>
        <h4>Strengths on tested criteria</h4>${list(
          (summary.strengths || []).map((c) => `${escape(c.name || c.id)}: ${score(c.score)}`),
          "No high-scoring tested categories established.",
        )}
        <h4>Risks in evaluated answers</h4>${list(
          (summary.risks || []).map((c) => `${escape(c.name || c.id)}: ${score(c.score)}`),
          "No low-scoring categories recorded in this sample. This does not prove there are no risks.",
        )}
        <h4>Missing evidence</h4>${list(
          (summary.missing_evidence || []).map(
            (c) => `${escape(c.name || c.id)}: ${escape(c.not_tested)} Not tested`,
          ),
          "None recorded.",
        )}
        <h4>Request reliability and speed</h4><p>${escape(summary.requests)} requests · ${escape(summary.errors)} errors · ${escape(summary.timeouts)} timeouts. Mean response time: ${summary.mean_seconds == null ? "Not measured" : escape(summary.mean_seconds) + " seconds"}.</p>
        <p>${escape(summary.request_metrics_basis)} All-case timings may include concurrent load.</p><p>Sequential speed-test average: ${summary.sequential_speed?.mean_seconds == null ? "Not measured" : escape(summary.sequential_speed.mean_seconds) + " seconds"} (${escape(summary.sequential_speed?.requests || 0)} requests).</p>
        <h4>Failing conversations</h4>${list(
          failures.map(
            (c) => `<strong>${escape(c.name)}</strong>: ${escape(c.results[slot].reason)}`,
          ),
          "No scored failing conversations recorded.",
        )}
        <p>Open Test evidence below for each exact conversation, expected behavior and judge explanation.</p></article>`;
      })
      .join("");
  };
})();
