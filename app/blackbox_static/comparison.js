window.renderAdvancedResults = function (run, names) {
  const esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const percent = (x) => (typeof x === "number" ? x.toFixed(1) + "%" : "Not measured");
  const panel = document.getElementById("comparison"),
    c = run.comparison;
  panel.hidden = !c;
  if (c) {
    const pairs = c.pairs || [];
    panel.innerHTML = `<h2>${c.winner ? "Overall winner: Bot " + esc(c.winner) : "No overall winner"}</h2><p>${esc(c.reason)}</p><h3>Head-to-head matrix</h3><div class="scroll"><table><thead><tr><th>Bot</th>${run.targets.map((t, i) => `<th>${"ABCD"[i]}: ${esc(t.name)}</th>`).join("")}</tr></thead><tbody>${run.targets
      .map(
        (t, i) =>
          `<tr><th>${"ABCD"[i]}: ${esc(t.name)}</th>${run.targets
            .map((u, j) => {
              const p = pairs.find((p) => [p.a, p.b].includes(i) && [p.a, p.b].includes(j));
              return `<td>${i === j ? "—" : p?.winner ? "Winner " + esc(p.winner) : p?.verdict === "too_close_to_call" ? "Too close to call" : "Insufficient evidence"}</td>`;
            })
            .join("")}</tr>`,
      )
      .join(
        "",
      )}</tbody></table></div>${pairs.map((p) => `<h3>${"ABCD"[p.a]} vs ${"ABCD"[p.b]}: ${esc(p.winner ? "Winner " + p.winner : p.verdict.replaceAll("_", " "))}</h3><p>Shared coverage: ${percent(p.coverage)}. ${p.confidence.low === null ? "Confidence interval unavailable" : `${(p.confidence.level * 100).toFixed(2)}% interval for net win advantage: ${(p.confidence.low * 100).toFixed(1)} to ${(p.confidence.high * 100).toFixed(1)} percentage points`} (${p.confidence.samples} distinct paired scenarios).</p><p>${esc(p.confidence.reason)}</p><table><thead><tr><th>Category</th><th>${"ABCD"[p.a]} wins</th><th>Ties</th><th>${"ABCD"[p.b]} wins</th><th>Not judged</th></tr></thead><tbody>${p.categories.map((x) => `<tr><td>${esc(names[x.category] || x.name)}</td><td>${x.a_wins}</td><td>${x.ties}</td><td>${x.b_wins}</td><td>${x.not_judged}</td></tr>`).join("")}</tbody></table>`).join("")}`;
  }
  document.getElementById("judge-agreement").innerHTML =
    "<h2>Second-judge agreement</h2>" +
    (run.judge_agreement || [])
      .map(
        (a) =>
          `<p><strong>${esc(a.target)}:</strong> ${percent(a.agreement_percent)} agreement; ${a.judged}/${a.sampled} sampled cases judged by both, ${a.unavailable} unavailable. Mean score difference: ${a.mean_absolute_score_difference ?? "Not measured"} points.</p><p class="help">${esc(a.definition)}</p>`,
      )
      .join("");
  document.getElementById("regressions").innerHTML =
    "<h2>Regression checks</h2>" +
    (run.regressions || [])
      .map(
        (r) =>
          `<article><h3>${esc(r.target)}: ${esc(r.status.replaceAll("_", " "))}</h3><p>${esc(r.reason || "Save a completed, sufficiently covered run as this bot’s baseline for future runs.")}</p>${r.categories?.length ? "<ul>" + r.categories.map((x) => `<li>${esc(names[x.category] || x.category)}: ${x.change_points ?? "Not measured"} points (${x.shared}/${x.planned} shared cases) ${r.status === "compared" && x.alert ? "<strong>Regression alert</strong>" : ""}</li>`).join("") + "</ul>" : ""}</article>`,
      )
      .join("");
};
