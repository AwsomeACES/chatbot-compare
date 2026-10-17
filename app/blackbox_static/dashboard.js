/* Dependency-free charts: available offline and backed only by recorded evidence. */
window.drawDashboard = function (run, names) {
  const root = document.getElementById("charts");
  const escape = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const palette = {
    passed: "#168064",
    failed: "#bd3650",
    not_tested: "#b47813",
    pending: "#b5becc",
  };
  const active = ["running", "queued"].includes(run.status);
  const html = run.targets
    .map((bot, index) => {
      const rows = run.cases.map((c) => c.results[index]);
      const counts = { passed: 0, failed: 0, not_tested: 0, pending: 0 };
      run.cases.forEach((c, i) => {
        const state = active && !c.completed ? "pending" : rows[i].status;
        counts[state in counts ? state : "not_tested"]++;
      });
      const total = rows.length,
        scored = counts.passed + counts.failed,
        s = run.summary[index];
      let offset = 0;
      const rings = Object.entries(counts)
        .filter(([, n]) => n)
        .map(([key, n]) => {
          const length = total ? (n / total) * 100 : 0;
          const part = `<circle r="15.9155" cx="21" cy="21" fill="none" stroke="${palette[key]}" stroke-width="6" stroke-dasharray="${length} ${100 - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 21 21)"><title>${key.replace("_", " ")}: ${n}</title></circle>`;
          offset += length;
          return part;
        })
        .join("");
      const legend = Object.entries(counts)
        .map(
          ([key, n]) =>
            `<li><span style="background:${palette[key]}"></span>${{ passed: "Passed", failed: "Needs improvement", not_tested: "Not tested", pending: "Waiting" }[key]} <strong>${n}</strong></li>`,
        )
        .join("");
      const bars = s.categories
        .map(
          (c) =>
            `<div class="category-bar"><span>${escape(names[c.id] || c.name)}</span><div class="bar-track"><div style="width:${Math.max(0, Math.min(100, c.score))}%"></div></div><strong>${typeof c.score === "number" ? c.score.toFixed(1) + "%" : "Not scored"}</strong><small>${c.tested}/${c.total} scored</small></div>`,
        )
        .join("");
      const times = rows
        .flatMap((r) => r.transcript || [])
        .map((t) => t.seconds)
        .filter((v) => typeof v === "number" && Number.isFinite(v) && v >= 0);
      const max = Math.max(1, ...times),
        points = times
          .map(
            (v, i) =>
              `${50 + (times.length === 1 ? 420 : (i / (times.length - 1)) * 840)},${180 - (v / max) * 140}`,
          )
          .join(" ");
      const chart = times.length
        ? `<svg class="latency-chart" viewBox="0 0 920 230" role="img" aria-label="Request durations in seconds. ${times.length} recorded requests, maximum ${max.toFixed(2)} seconds."><line x1="50" y1="180" x2="890" y2="180" stroke="#9ca7ba"/><line x1="50" y1="40" x2="50" y2="180" stroke="#9ca7ba"/><text x="2" y="45">${max.toFixed(1)}s</text><text x="15" y="183">0s</text><polyline points="${points}" fill="none" stroke="#5352bd" stroke-width="3"/>${times.map((v, i) => `<circle cx="${50 + (times.length === 1 ? 420 : (i / (times.length - 1)) * 840)}" cy="${180 - (v / max) * 140}" r="3" fill="#5352bd"><title>Request ${i + 1}: ${v.toFixed(2)} seconds</title></circle>`).join("")}<text x="50" y="210">Request 1</text><text x="790" y="210">Request ${times.length}</text></svg>`
        : '<p class="chart-empty">No request timings recorded yet. The graph appears after a real request.</p>';
      return `<section class="dashboard-bot"><h3>${escape(bot.name)}</h3><div class="stat-grid"><div class="card"><small>${active ? "Score so far" : "Evaluation score"}</small><strong>${typeof s.score === "number" ? s.score.toFixed(1) + "%" : "Not scored"}</strong><span>${scored}/${total} cases scored (${s.coverage}% coverage)</span></div><div class="card"><small>Tests needing improvement</small><strong>${counts.failed}</strong><span>Open the conversations below</span></div><div class="card"><small>Not tested${active ? " / waiting" : ""}</small><strong>${counts.not_tested + counts.pending}</strong><span>Excluded from quality; reduces coverage</span></div></div><div class="chart-grid"><article class="card"><h3>Test outcomes</h3><div class="donut-wrap"><svg class="donut" viewBox="0 0 42 42" role="img" aria-label="${escape(
        Object.entries(counts)
          .map(([k, v]) => k + ": " + v)
          .join(", "),
      )}"><circle cx="21" cy="21" r="15.9155" fill="none" stroke="#e6eaf2" stroke-width="6"/>${rings}<text x="21" y="21" text-anchor="middle" dominant-baseline="middle" font-size="6" fill="#172033">${total}</text><text x="21" y="27" text-anchor="middle" font-size="3" fill="#465268">planned cases</text></svg><ul class="chart-legend">${legend}</ul></div></article><article class="card"><h3>Scores by test category</h3>${bars}<p class="help">Higher is better. Unscored cases reduce coverage only. Ranking needs sufficient evidence in every selected category.</p></article></div><article class="card"><h3>Response time — seconds</h3>${chart}<p class="help">Recorded request order within the displayed cases. This chart shows current attempts; reliability totals include prior attempts when recorded.</p></article></section>`;
    })
    .join("");
  if (root._html !== html) {
    root.innerHTML = html;
    root._html = html;
  }
};
