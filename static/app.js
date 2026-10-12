const $ = (id) => document.getElementById(id);
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
const METRICS = [
  ["overall", "Overall"], ["accuracy", "Accuracy"], ["safety", "Safety"], ["hallucination", "No hallucination"],
  ["bias", "Fairness (bias)"], ["quality", "Judge quality"], ["speed", "Speed"],
];
let bots = [], presets = [], suites = [], judgeInfo = {}, currentRunId = null, pollTimer = null, currentRun = null;

// ---------- Utilities ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function md(s) { // tiny, safe markdown: **bold** only; newlines kept via CSS
  return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || `HTTP ${res.status}`), { status: res.status });
  return data;
}
const fmt = (v, d = 0) => (v == null ? "—" : Number(v).toFixed(d));
const pct = (v) => (v == null ? "—" : fmt(v) + "%");
const usd = (v) => (v == null ? "—" : "$" + (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(3)));
const secs = (ms) => (ms == null ? "—" : (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + "s");
function tryStore(k, v) { try { v === undefined ? localStorage.getItem(k) : localStorage.setItem(k, v); } catch {} }
function readStore(k) { try { return localStorage.getItem(k); } catch { return null; } }

// ---------- Theme & tabs ----------
(function initTheme() {
  const saved = readStore("theme");
  if (saved) document.documentElement.dataset.theme = saved;
  $("themeBtn").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    tryStore("theme", document.documentElement.dataset.theme);
  };
})();

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
  if (name === "arena") loadLeaderboard();
  if (name === "review") loadReview();
  if (name === "governance") loadGovernance();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

// ---------- Tooltip ----------
const tip = $("tooltip");
function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; moveTip(e); }
function moveTip(e) {
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { tip.hidden = true; }
function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mouseenter", (e) => showTip(e, el.dataset.tip));
    el.addEventListener("mousemove", moveTip);
    el.addEventListener("mouseleave", hideTip);
  });
}

// ---------- Evaluate tab ----------
function botRow(b, checked, name) {
  const label = document.createElement("label");
  label.className = "bot";
  label.innerHTML = `<input type="checkbox" name="${name}" value="${esc(b.id)}" ${checked ? "checked" : ""}>
    <span><div class="name">${esc(b.label)}</div><div class="desc">${esc(b.description || b.type)}</div></span>
    <button type="button" class="ping">Test</button><div class="ping-result muted" hidden></div>`;
  const out = label.querySelector(".ping-result");
  label.querySelector(".ping").onclick = async (e) => {
    e.preventDefault();
    out.hidden = false; out.textContent = "Sending “Hi”…";
    try {
      const r = await api(`/api/bots/${encodeURIComponent(b.id)}/ping`, { method: "POST" });
      out.innerHTML = r.ok
        ? `<span class="status pass"><span class="dot">✓</span></span> ${secs(r.latency_ms)} · “${esc(r.reply.slice(0, 90))}”`
        : `<span class="status fail"><span class="dot">✕</span></span> ${esc(r.error)}`;
    } catch (err) { out.textContent = err.message; }
  };
  return label;
}

async function loadSetup() {
  [{ bots, presets, judge: judgeInfo }, { suites }] = await Promise.all([api("/api/bots"), api("/api/suites")]);
  $("judgeName").textContent = judgeInfo.model;
  $("secondJudgeName").textContent = judgeInfo.second_judge ? `(${judgeInfo.second_judge})` : "(not configured: set SECOND_JUDGE_MODEL)";
  let picked = [];
  try { picked = JSON.parse(readStore("picked") || "[]"); } catch {}
  if (!picked.length) picked = bots.slice(0, 2).map((b) => b.id);
  $("botList").replaceChildren(...bots.map((b) => botRow(b, picked.includes(b.id), "pick")));
  $("arenaPool").replaceChildren(...bots.map((b) => botRow(b, picked.includes(b.id), "pool")));
  $("botList").addEventListener("change", updatePickCount);
  renderPresets();
  updatePickCount();
  syncJudgeOptions();
  $("suiteSelect").innerHTML = suites.map((s) => `<option value="${esc(s.id)}">${esc(s.name)} (${s.cases} cases)</option>`).join("");
  $("suiteSelect").onchange = showSuiteInfo;
  showSuiteInfo();
}
function picked(name) { return [...document.querySelectorAll(`input[name=${name}]:checked`)].map((i) => i.value); }
function updatePickCount() {
  const ids = picked("pick"), n = ids.length;
  $("pickCount").textContent = `(${n} selected)`;
  $("startBtn").disabled = n < 2 || n > 4;
  $("runTypeHint").textContent = runTypeOf(ids);
  document.querySelectorAll("#presetList button").forEach((b) => b.setAttribute("aria-pressed",
    String(b.dataset.bots === [...ids].sort().join(","))));
  tryStore("picked", JSON.stringify(ids));
}
// Same rule as evaluator.run_type: what a comparison of these bots can tell you.
function runTypeOf(ids) {
  const sel = bots.filter((b) => ids.includes(b.id));
  if (sel.length < 2) return "";
  if (sel.some((b) => !b.app || !b.llm)) return "Set \"llm\" on every bot in bots.json to label what this run compares.";
  const apps = new Set(sel.map((b) => b.app)), llms = new Set(sel.map((b) => b.llm));
  if (llms.size === 1 && apps.size > 1) return `Same model (${[...llms][0]}), different apps: compares the apps.`;
  if (apps.size === 1 && llms.size > 1) return "Same app, different models: compares the models.";
  if (apps.size === 1) return "Same app and model: measures run-to-run variation.";
  return "Different apps on different models: compares whole products, not the apps alone. Pick a same-model preset to compare apps.";
}
function renderPresets() {
  $("presetList").replaceChildren(...presets.map((p) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "preset"; b.textContent = p.label;
    b.dataset.bots = [...p.bots].sort().join(",");
    b.title = p.missing.length ? `Enable ${p.missing.join(", ")} in bots.json to use this preset` : (p.description || "");
    b.disabled = p.missing.length > 0;
    b.onclick = () => {
      document.querySelectorAll("input[name=pick]").forEach((i) => (i.checked = p.bots.includes(i.value)));
      updatePickCount();
    };
    return b;
  }));
}
function syncJudgeOptions() {
  for (const id of ["compareToggle", "secondJudgeToggle"]) $(id).disabled = !$("judgeToggle").checked;
  if (!judgeInfo.second_judge) { $("secondJudgeToggle").disabled = true; $("secondJudgeToggle").checked = false; }
}
$("judgeToggle").onchange = syncJudgeOptions;
function showSuiteInfo() {
  const s = suites.find((x) => x.id === $("suiteSelect").value);
  $("suiteInfo").textContent = s ? `${s.description} Skills: ${s.categories.join(", ")}.` : "";
  const n = s?.rewordings || 0;
  $("rewordToggle").disabled = !n;
  if (!n) $("rewordToggle").checked = false;
  $("rewordInfo").textContent = n ? `(${s.reworded_cases} cases × their rewordings = ${n} more chats per bot)`
    : "(this suite has none yet: run reword.py)";
}

$("startBtn").onclick = async () => {
  $("startError").textContent = "";
  $("startBtn").disabled = true;
  try {
    const { id } = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        bots: picked("pick"), suite: $("suiteSelect").value, judge: $("judgeToggle").checked,
        repeats: Number($("repeatSelect").value), comparative: $("compareToggle").checked,
        second_judge: $("secondJudgeToggle").checked, rewordings: $("rewordToggle").checked,
      }),
    });
    openRun(id);
    loadRuns();
  } catch (e) { $("startError").textContent = e.message; }
  finally { updatePickCount(); }
};

async function loadRuns() {
  const { runs } = await api("/api/runs");
  if (!runs.length) { $("runList").innerHTML = `<p class="muted">No runs yet.</p>`; return; }
  $("runList").replaceChildren(...runs.map((r) => {
    const row = document.createElement("div");
    row.className = "run-row"; row.tabIndex = 0; row.setAttribute("role", "button");
    const status = r.status === "done"
      ? (r.winner ? `Winner: ${esc(r.winner.label)}` : "done")
      : r.status === "running" ? `running ${r.progress.done}/${r.progress.total}` : r.status;
    const rg = r.regressions, marks = (r.baseline_for.length ? `<span class="pill base">baseline</span>` : "")
      + (rg?.compared ? (rg.critical ? `<span class="pill crit">${rg.critical} critical</span>` : rg.warnings
        ? `<span class="pill warn">${rg.warnings} warning${rg.warnings > 1 ? "s" : ""}</span>` : `<span class="pill ok">no regressions</span>`) : "")
      + Object.entries(r.signoffs || {}).map(([id, d]) => `<span class="pill ${d === "approve" ? "ok" : "crit"}">${esc(r.bots.find((b) => b.id === id)?.label || id)} ${d === "approve" ? "approved" : "rejected"}</span>`).join("");
    row.innerHTML = `<span><b>${r.bots.map((b) => esc(b.label)).join(" vs ")}</b> ${marks}<br>
      <span class="muted small">${esc(r.suite_name)} · ${esc(r.created_at.replace("T", " "))}${r.judge ? " · AI judge" : ""}${r.repeats > 1 ? ` · ×${r.repeats} repeats` : ""}${r.rewordings ? " · rewordings" : ""}</span></span>
      <span class="pill">${status}</span><button class="del" type="button" title="Delete run" aria-label="Delete run">✕</button>`;
    row.onclick = () => openRun(r.id);
    row.onkeydown = (e) => { if (e.key === "Enter") openRun(r.id); };
    row.querySelector(".del").onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this run?")) return;
      await api(`/api/runs/${r.id}`, { method: "DELETE" });
      if (currentRunId === r.id) { currentRunId = null; $("results").hidden = true; $("resultsEmpty").hidden = false; }
      loadRuns();
    };
    return row;
  }));
}

// ---------- Results tab ----------
function openRun(id) {
  currentRunId = id;
  clearTimeout(pollTimer);
  showTab("results");
  refreshRun();
}
async function refreshRun() {
  const id = currentRunId;
  let run;
  try {
    run = await api(`/api/runs/${id}`);
  } catch (e) { // server restarting or briefly unreachable: say so and keep trying
    if (id !== currentRunId) return;
    $("progressText").textContent = `Can't reach the server (${e.message}). Retrying…`;
    pollTimer = setTimeout(refreshRun, 5000);
    return;
  }
  if (id !== currentRunId) return;
  currentRun = run;
  renderRun(run);
  if (run.status === "running") pollTimer = setTimeout(refreshRun, 2000);
  else { loadRuns(); renderRegressions(run); renderGate(run); }
}

function colorOf(run, botId) { return SERIES[run.bots.findIndex((b) => b.id === botId) % SERIES.length]; }

function renderRun(run) {
  $("resultsEmpty").hidden = true; $("results").hidden = false;
  $("runTitle").textContent = run.bots.map((b) => b.label).join("  vs  ");
  $("runMeta").textContent = [
    run.suite_name, run.created_at.replace("T", " "),
    run.run_type?.label,
    (run.repeats || 1) > 1 ? `every case ×${run.repeats}` : null,
    run.judge ? `AI judge: ${run.judge_model}${run.judge_prompt_version ? ` (prompt ${run.judge_prompt_version})` : ""}` : "no AI judge (exact checks only)",
    run.comparative ? "comparative judge" : null,
    run.second_judge_model ? `second judge: ${run.second_judge_model}` : null,
    run.rewordings ? "injection and bias cases also asked in their rewordings" : null,
    run.failure ? `failed: ${run.failure}` : null,
  ].filter(Boolean).join(" · ");
  const { done, total } = run.progress;
  $("progressWrap").hidden = run.status === "done";
  $("progressBar").style.width = `${(100 * done) / Math.max(total, 1)}%`;
  $("progressText").textContent = run.status !== "running" ? run.status
    : run.phase === "comparing" ? `Comparing answers side by side… ${done} of ${total}` : `Running… ${done} of ${total} conversations`;

  $("exportLinks").hidden = run.status === "running";
  $("csvLink").href = `/api/runs/${encodeURIComponent(run.id)}/export.csv`;
  $("pdfLink").href = `/api/runs/${encodeURIComponent(run.id)}/report.html`;
  const s = run.summary;
  $("outcomeNote").innerHTML = s ? s.bots.filter((b) => b.outcomes).map((b) => `<div><span class="swatch" style="background:${colorOf(run, b.id)}"></span><b>${esc(b.label)}</b>
    <span class="pill ok">${b.outcomes.pass} passed</span><span class="pill crit">${b.outcomes.fail} failed</span>
    ${b.outcomes.error ? `<span class="pill crit">${b.outcomes.error} errors</span>` : ""}
    ${b.outcomes.blocked ? `<span class="pill warn">${b.outcomes.blocked} blocked (quota)</span>` : ""}
    ${b.outcomes["not supported"] ? `<span class="pill">${b.outcomes["not supported"]} not supported</span>` : ""}
    ${b.outcomes["not graded"] ? `<span class="pill">${b.outcomes["not graded"]} not graded</span>` : ""}</div>`).join("") : "";
  if (s) {
    renderTiles(run, s);
    renderScoreTable(run, s);
    renderLegend("legendScores", run); renderLegend("legendCats", run);
    const series = run.bots.map((b) => ({ id: b.id, label: b.label, color: colorOf(run, b.id) }));
    const byId = Object.fromEntries(s.bots.map((b) => [b.id, b]));
    const metrics = METRICS.filter(([k]) => s.bots.some((b) => b[k] != null));
    groupedBars($("chartScores"), metrics.map(([, l]) => l), series,
      metrics.map(([k]) => series.map((x) => byId[x.id][k])), { max: 100, labelGroups: [0] });
    groupedBars($("chartCats"), s.categories, series,
      s.categories.map((c) => series.map((x) => byId[x.id].by_category[c])), { max: 100, unit: "%" });
    latencyBars($("chartLatency"), series.map((x) => ({ ...x, p50: byId[x.id].latency_p50, p95: byId[x.id].latency_p95 })));
    renderPairs(run, s);
    renderCost(run, s);
  } else {
    $("tiles").innerHTML = ""; $("scoreTable").innerHTML = ""; $("unsupportedNote").textContent = "";
    $("judgeNote").textContent = ""; $("pairCard").hidden = true; $("regressCard").hidden = true; $("gateCard").hidden = true;
    $("costCard").hidden = true;
    ["chartScores", "chartCats", "chartLatency", "legendScores", "legendCats"].forEach((i) => ($(i).innerHTML = ""));
    if (run.status === "running") $("tiles").innerHTML = `<div class="tile hero"><div class="label">Scores</div><div class="sub">Charts appear when the run finishes. Case results fill in below as they arrive.</div></div>`;
  }
  renderCases(run);
}

// ---------- Regression check against each bot's baseline run ----------
async function renderRegressions(run) {
  const card = $("regressCard");
  if (run.status !== "done") { card.hidden = true; return; }
  let rep;
  try { rep = await api(`/api/runs/${run.id}/regressions`); } catch { card.hidden = true; return; }
  if (run.id !== currentRunId) return;
  const isBase = rep.bots.some((b) => b.status === "is_baseline");
  const head = !rep.compared ? ["info", isBase ? "This run is the baseline" : "No baseline to compare with"]
    : rep.critical ? ["crit", `${rep.critical} critical regression${rep.critical > 1 ? "s" : ""}${rep.warnings ? `, ${rep.warnings} warning${rep.warnings > 1 ? "s" : ""}` : ""}`]
    : rep.warnings ? ["warn", `${rep.warnings} warning${rep.warnings > 1 ? "s" : ""}, nothing critical`]
    : ["ok", "No regressions against the baseline"];
  const status = {
    is_baseline: "is the baseline (this run)", no_baseline: "has no baseline yet",
    baseline_missing: "its baseline run was deleted", different_suite: "its baseline used a different suite",
    older_than_baseline: "this run is older than its baseline",
  };
  const caseLink = (x) => `<a href="#" data-case="${esc(x.case_id)}">${esc(x.case_id)}</a>`;
  const deltas = (d) => Object.entries(d).filter(([, v]) => v.delta !== 0)
    .map(([k, v]) => `${k} ${fmt(v.before, 1)} → ${fmt(v.now, 1)} <span class="${v.delta > 0 ? "up" : "down"}">(${v.delta > 0 ? "+" : ""}${fmt(v.delta, 1)})</span>`).join(" · ");
  const bots = rep.bots.map((b) => {
    if (b.status !== "compared") return `<li><b>${esc(b.label)}</b> ${status[b.status] || esc(b.status)}</li>`;
    return `<li><b>${esc(b.label)}</b> vs <a href="#" data-run="${esc(b.baseline)}">baseline of ${esc(b.baseline_created.replace("T", " "))}</a>`
      + (b.suite_changed ? ` <span class="muted small">(suite changed since; cases compared where both runs have them, scores not compared)</span>` : "")
      + (b.alerts.length ? `<ul>${b.alerts.map((a) => `<li class="${a.level === "critical" ? "crit" : "warn"}">${a.level === "critical" ? "Critical" : "Warning"}: ${esc(a.text)}</li>`).join("")}</ul>` : " — ok")
      + (b.broken.length ? `<div class="small">Broke: ${b.broken.map(caseLink).join(", ")}</div>` : "")
      + (b.fixed.length ? `<div class="small">Fixed: ${b.fixed.map(caseLink).join(", ")}</div>` : "")
      + (b.new_failing.length ? `<div class="small">New cases failing: ${b.new_failing.map(caseLink).join(", ")}</div>` : "")
      + (Object.keys(b.deltas).length ? `<div class="small muted">${deltas(b.deltas)}</div>` : "") + `</li>`;
  }).join("");
  card.hidden = false;
  card.innerHTML = `<div class="cases-head"><h2>Regression check</h2><span>
      ${isBase ? `<button type="button" class="ghost" id="unbaseBtn">Stop using as baseline</button>` : ""}
      <button type="button" class="ghost" id="baseBtn">${isBase ? "Baseline" : "Set as baseline"}</button></span></div>
    <p class="banner ${head[0]}">${head[1]}</p><ul class="regress-list">${bots}</ul>
    <p class="muted small">A case breaks when it passed in the bot's baseline run and fails now (with repeats: its pass share fell by half or more).
    Critical = a safety, hallucination or bias case broke. Warnings: another case broke, overall fell below the baseline's 95% range,
    accuracy or judge quality fell 5+ points, or speed fell 10+. Set a run as the baseline to compare later runs with it.</p>`;
  $("baseBtn").disabled = isBase && rep.bots.every((b) => b.status === "is_baseline");
  $("baseBtn").onclick = async () => { await api(`/api/runs/${run.id}/baseline`, { method: "POST" }); renderRegressions(run); loadRuns(); };
  if (isBase) $("unbaseBtn").onclick = async () => { await api(`/api/runs/${run.id}/baseline`, { method: "DELETE" }); renderRegressions(run); loadRuns(); };
  card.querySelectorAll("a[data-run]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openRun(a.dataset.run); }));
  card.querySelectorAll("a[data-case]").forEach((a) => (a.onclick = (e) => {
    e.preventDefault();
    $("catFilter").value = ""; $("caseFilter").value = "";
    openCase = a.dataset.case; renderCases(currentRun);
    document.querySelector(`tr[data-case="${CSS.escape(a.dataset.case)}"]`)?.scrollIntoView({ block: "center" });
  }));
}

// ---------- Release gate and sign-off (governance.json) ----------
const VERDICT = { pass: ["ok", "Pass"], warn: ["warn", "Pass with warnings"], fail: ["crit", "Blocked"] };
function ruleList(rules, all) {
  const shown = all ? rules : rules.filter((r) => r.ok === false);
  if (!shown.length) return `<div class="small muted">Every rule passed.</div>`;
  return `<ul class="gate-rules">${shown.map((r) => `<li class="${r.ok === false ? (r.level === "block" ? "crit" : "warn") : r.ok ? "ok" : "na"}">`
    + `<span class="mark" aria-hidden="true">${r.ok === false ? "✕" : r.ok ? "✓" : "–"}</span>`
    + `<span>${r.ok === false ? `<b>${r.level === "block" ? "Blocks" : "Warning"}:</b> ` : ""}${esc(r.text)}</span></li>`).join("")}</ul>`;
}
async function renderGate(run) {
  const card = $("gateCard");
  if (run.status !== "done") { card.hidden = true; return; }
  let g;
  try { g = await api(`/api/runs/${run.id}/gate`); } catch { card.hidden = true; return; }
  if (run.id !== currentRunId) return;
  const integrity = { intact: ["ok", "Results unchanged since the run was recorded"], modified: ["crit", "Results were changed after the run was recorded"],
    unsealed: ["info", "Run predates the audit log; its results can't be verified"] }[g.integrity] || ["info", ""];
  const last = (id) => g.signoffs.filter((s) => s.bot_id === id).at(-1);
  card.hidden = false;
  card.innerHTML = `<div class="cases-head"><h2>Release gate <span class="muted small">policy v${esc(g.policy_version)}</span></h2>
      <span class="pill ${integrity[0]}">${integrity[1]}</span></div>
    <div class="gate-bots">${g.bots.map((b) => {
      const s = last(b.id), v = VERDICT[b.verdict];
      return `<div class="gate-bot" data-bot="${esc(b.id)}">
        <div class="cases-head"><h3>${esc(b.label)}</h3><span class="pill ${v[0]}">${v[1]}</span></div>
        ${ruleList(b.rules, false)}
        <details><summary class="small">All ${b.rules.length} rules</summary>${ruleList(b.rules, true)}</details>
        ${s ? `<p class="small"><b>${s.decision === "approve" ? "Approved" : "Rejected"}</b> by ${esc(s.reviewer)} on ${esc(s.at.replace("T", " "))}${s.override ? ` <span class="pill crit">override</span>` : ""}${s.note ? `: “${esc(s.note)}”` : ""}</p>` : ""}
        <div class="label-form signoff">
          <input type="text" class="reviewer" placeholder="Reviewer name" aria-label="Reviewer name" value="${esc(readStore("reviewer") || "")}">
          <input type="text" class="note" placeholder="${b.verdict === "fail" ? "Justification (needed to override)" : "Note (optional)"}" aria-label="Note">
          ${b.verdict === "fail" ? `<label class="check inline-check small"><input type="checkbox" class="override"> Override the gate</label>` : ""}
          <button type="button" class="primary approve">Approve for release</button>
          <button type="button" class="ghost reject">Reject</button>
          <span class="small error msg-out" role="status"></span>
        </div></div>`;
    }).join("")}</div>
    <p class="muted small">A bot can be approved only when no <b>blocking</b> rule fails, unless a reviewer overrides the gate with a written justification. Every decision is saved with the gate result, the policy version and the hash of this run's results, and written to the audit log.</p>`;
  card.querySelectorAll(".gate-bot").forEach((el) => {
    const out = el.querySelector(".msg-out");
    const send = async (decision) => {
      const reviewer = el.querySelector(".reviewer").value.trim();
      if (!reviewer) { out.textContent = "Enter the reviewer's name."; return; }
      tryStore("reviewer", reviewer);
      try {
        await api(`/api/runs/${run.id}/signoff`, { method: "POST", body: JSON.stringify({
          bot_id: el.dataset.bot, decision, reviewer, note: el.querySelector(".note").value,
          override: !!el.querySelector(".override")?.checked }) });
        renderGate(run); loadRuns();
      } catch (e) { out.textContent = e.message; }
    };
    el.querySelector(".approve").onclick = () => send("approve");
    el.querySelector(".reject").onclick = () => send("reject");
  });
}

// ---------- Governance tab ----------
const RISK_STATUS = { ok: ["ok", "OK"], breach: ["crit", "Breach"], "no data": ["", "No data"], manual: ["warn", "Manual check"] };
async function loadGovernance() {
  let ov;
  try { ov = await api("/api/governance"); } catch (e) { $("govRelease").innerHTML = `<tbody><tr><td class="error">${esc(e.message)}</td></tr></tbody>`; return; }
  const p = ov.policy, gate = p.release_gate || {};
  $("govPolicy").innerHTML = `Policy v${esc(p.version)} (sha256 ${esc((p.sha256 || "").slice(0, 12))}) · minimums: `
    + Object.entries(gate.min_scores || {}).map(([k, v]) => `${esc(k)} ${v}`).join(", ")
    + Object.entries(gate.max_failed_cases || {}).map(([k, v]) => ` · at most ${v} failed ${esc(k)} case${v === 1 ? "" : "s"}`).join("")
    + (gate.max_critical_regressions != null ? ` · at most ${gate.max_critical_regressions} critical regressions` : "")
    + ` · approved bot LLMs: ${(p.models?.bot_llms || []).map(esc).join(", ")} · judges: ${(p.models?.judges || []).map(esc).join(", ")}`;
  $("govRelease").innerHTML = `<thead><tr><th>Bot</th><th>LLM</th><th>Latest run</th><th>Gate</th><th>What fails</th><th>Sign-off</th></tr></thead><tbody>`
    + ov.bots.map((b) => {
      const v = b.gate && VERDICT[b.gate.verdict], s = b.signoff;
      const fails = b.gate ? b.gate.rules.filter((r) => r.ok === false && r.level === "block").map((r) => esc(r.text)).join("<br>") : "";
      return `<tr><td>${esc(b.label)}</td><td>${esc(b.llm || "—")}</td>
        <td>${b.run ? `<a href="#" data-run="${esc(b.run.id)}">${esc(b.run.created_at.replace("T", " "))}</a>` : `<span class="muted">no finished run</span>`}</td>
        <td>${v ? `<span class="pill ${v[0]}">${v[1]}</span>` : "—"}</td><td class="small">${fails || (b.gate ? `<span class="muted">nothing blocks</span>` : "")}</td>
        <td class="small">${s ? `<span class="pill ${s.decision === "approve" ? "ok" : "crit"}">${s.decision === "approve" ? "approved" : "rejected"}</span> ${esc(s.reviewer)}, ${esc(s.at.slice(0, 10))}${s.override ? " (override)" : ""}${s.policy_changed ? `<br><span class="muted">policy changed since</span>` : ""}` : `<span class="muted">none</span>`}</td></tr>`;
    }).join("") + `</tbody>`;
  $("govRelease").querySelectorAll("a[data-run]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); openRun(a.dataset.run); }));
  $("govRisks").innerHTML = `<thead><tr><th>ID</th><th>Risk</th><th>Severity</th><th>Target</th><th>Frameworks</th>${ov.bots.map((b) => `<th>${esc(b.label)}</th>`).join("")}</tr></thead><tbody>`
    + ov.risks.map((r) => `<tr><td>${esc(r.id)}</td><td>${esc(r.title)}<div class="small muted">${esc(r.mitigation || "")}</div></td>
      <td><span class="pill ${r.severity === "high" ? "crit" : r.severity === "medium" ? "warn" : ""}">${esc(r.severity || "")}</span></td>
      <td class="small">${esc(r.metric)}${r.min != null ? ` ≥ ${r.min}` : r.max != null ? ` ≤ ${r.max}` : ""}</td>
      <td class="small">${(r.frameworks || []).map(esc).join("<br>")}</td>
      ${ov.bots.map((b) => { const st = r.status[b.id], k = RISK_STATUS[st.status] || ["", st.status];
        return `<td><span class="pill ${k[0]}">${k[1]}</span>${st.value != null && st.value !== "" ? `<div class="small muted">${esc(st.value)}</div>` : ""}</td>`; }).join("")}</tr>`).join("") + `</tbody>`;
  $("govCards").replaceChildren(...ov.bots.map((b) => {
    const c = b.card, e = c.evaluation, d = document.createElement("details");
    d.className = "model-card";
    const row = (k, v) => v == null || v === "" ? "" : `<tr><th>${k}</th><td>${v}</td></tr>`;
    d.innerHTML = `<summary><b>${esc(b.label)}</b> <span class="muted small">${esc(c.name)} · owner ${esc(c.owner || "—")}</span></summary>
      <table class="score card-table"><tbody>
        ${row("Intended use", esc(c.intended_use))}${row("Users", esc(c.users))}${row("Out of scope", esc(c.out_of_scope))}${row("Risk class", esc(c.risk_class))}
        ${row("Model", `${esc(c.model.llm || "—")} <span class="muted">(${esc(c.model.model_id || "—")}, ${esc(c.model.adapter)}; ${c.model.paid ? "paid" : "free"}; ${c.model.approved ? "approved" : `<b class="error">not in the approved inventory</b>`})</span>`)}
        ${row("Data", `store profile <code>${esc(c.data.profile || "—")}</code> · debug trace ${c.data.trace ? "on" : "off"}`)}
        ${e ? row("Evaluation", `run ${esc(e.run_id)} on ${esc(e.date.slice(0, 10))} · ${esc(e.suite || "")} · judge ${esc(e.judge_model || "—")} · ×${e.repeats}${e.rewordings ? " · rewordings" : ""}`)
          + row("Scores", Object.entries(e.scores).filter(([, v]) => v != null).map(([k, v]) => `${esc(k)} <b>${fmt(v, 1)}</b>`).join(" · ")
            + (e.overall_range ? ` <span class="muted">(overall 95% range ${fmt(e.overall_range[0], 1)}–${fmt(e.overall_range[1], 1)})</span>` : ""))
          + row("Provenance", e.provenance ? `commit ${esc((e.provenance.git_commit || "—").slice(0, 10))}${e.provenance.git_dirty ? " (uncommitted changes)" : ""} · suite ${esc((e.provenance.suite_sha256 || "").slice(0, 12))} · policy v${esc(e.provenance.policy_version)} · started by ${esc(e.provenance.started_by)}` : `<span class="muted">not recorded (run predates governance)</span>`)
          : row("Evaluation", `<span class="muted">no finished run yet</span>`)}
        ${row("Known limitations", c.limitations.length ? c.limitations.map(esc).join("<br>") : `<span class="muted">none found in the latest run</span>`)}
        ${row("Human oversight", `${c.oversight.human_review_labels} judge-review labels · judge spot-check accuracy ${c.oversight.judge_spot_accuracy != null ? fmt(c.oversight.judge_spot_accuracy, 1) + "%" : "—"}`)}
      </tbody></table>`;
    return d;
  }));
  const ret = ov.retention, data = p.data || {};
  $("govData").innerHTML = `<p><b>Personal data:</b> ${esc(data.pii)} — ${data.pii === "redact" ? "personal data that appears only in a bot's reply is masked before the conversation is sent to a cloud judge, and counted on the case."
      : data.pii === "flag" ? "personal data is counted on each case but sent to the judge as is." : "not checked."}
      Values already in the store data or test case are synthetic test data and are sent as is.</p>
    <p><b>Retention:</b> ${ret.retention_days ? `runs older than ${ret.retention_days} days are deleted (nightly), except baselines and signed-off runs. ${ret.runs.length} due now, ${ret.kept} kept as evidence.` : "no limit set."}</p>
    ${ret.runs.length ? `<button type="button" class="ghost" id="purgeBtn">Delete ${ret.runs.length} expired run${ret.runs.length > 1 ? "s" : ""} now</button>` : ""}
    <p class="muted small">Run <code>compliance.py scan</code> to list the personal-data-shaped values in the suites and store data files; all of them must be synthetic.</p>`;
  if ($("purgeBtn")) $("purgeBtn").onclick = async () => {
    if (!confirm(`Delete ${ret.runs.length} run(s) older than ${ret.retention_days} days?`)) return;
    await api("/api/governance/purge", { method: "POST", body: JSON.stringify({ dry_run: false }) });
    loadGovernance(); loadRuns();
  };
  let audit = { entries: [] };
  try { audit = await api("/api/audit?limit=30"); } catch {}
  const a = ov.audit;
  $("govAudit").innerHTML = `<p class="banner ${a.ok ? "ok" : "crit"}">${a.ok ? `Hash chain intact · ${a.entries} entries` : `Hash chain broken: ${esc(a.problem)}`}</p>
    <div class="audit-list">${audit.entries.map((e) => `<div class="small"><span class="muted">#${e.seq} ${esc(e.at.replace("T", " ").replace("Z", " UTC"))}</span> <b>${esc(e.action)}</b> ${esc(e.target || "")} <span class="muted">by ${esc(e.actor)}</span></div>`).join("") || `<p class="muted small">No entries yet.</p>`}</div>
    <p class="muted small">Every run, baseline change, judge label, sign-off and purge is appended to <code>runs/audit.jsonl</code>; each line carries the hash of the one before, so an edited or deleted line breaks the chain. Verify from the terminal with <code>compliance.py audit</code>.</p>`;
}

function renderLegend(elId, run) {
  $(elId).innerHTML = run.bots.map((b) => `<span><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</span>`).join("");
}

const byRank = (bots) => [...bots].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));

function renderTiles(run, s) {
  const ranked = byRank(s.bots).filter((b) => b.rank != null);
  const w = ranked[0];
  // Older summaries have no bootstrap; fall back to the fixed 3-point margin they used.
  const close = s.winner && (s.winner.clear != null ? !s.winner.clear : s.winner.margin != null && s.winner.margin < 3);
  const range = (b) => b.overall_range ? ` (range ${fmt(b.overall_range[0])}–${fmt(b.overall_range[1])})` : "";
  const sure = s.winner?.confidence != null ? ` It leads in ${fmt(100 * s.winner.confidence)}% of ${s.bootstrap} resamples of the cases`
    + (close ? `, below the ${fmt(100 * s.clear_win)}% needed to call it.` : ".") : "";
  const hero = w
    ? `<div class="tile hero"><div class="label">${close ? "Too close to call — leader" : "Winner"}</div>
    <div class="value"><span class="swatch" style="background:${colorOf(run, w.id)}"></span>${esc(w.label)}</div>
    <div class="sub">Overall ${fmt(w.overall, 1)} / 100${range(w)}${s.winner.margin != null ? ` · ${fmt(s.winner.margin, 1)} points ahead of ${esc(ranked[1].label)}${range(ranked[1])}` : ""}.${sure}</div></div>`
    : `<div class="tile hero"><div class="label">No winner</div><div class="value">Not enough cases scored</div>
    <div class="sub">A bot is ranked once at least ${fmt(s.min_coverage ?? 80)}% of its cases were scored. Re-run when quotas reset.</div></div>`;
  const best = (k, better = "max") => {
    const vals = s.bots.filter((b) => b[k] != null && b.rank != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => ((better === "max" ? b[k] > a[k] : b[k] < a[k]) ? b : a));
  };
  const tile = (label, b, val, sub) => b ? `<div class="tile"><div class="label">${label}</div><div class="value">${val}</div>
    <div class="sub"><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}${sub ? " · " + sub : ""}</div></div>` : "";
  const acc = best("accuracy"), safe = best("safety"), hal = best("hallucination"), bias = best("bias"), q = best("quality"), fast = best("latency_p50", "min");
  const robust = best("robustness");
  const priced = s.bots.filter((b) => b.cost?.cost_per_100 != null && b.rank != null);
  const cheap = priced.length ? priced.reduce((a, b) => (b.cost.cost_per_100 < a.cost.cost_per_100 ? b : a)) : null;
  const flagged = (b, k) => b && b[k]?.length ? `fails ${b[k].length}` : "none failed";
  $("tiles").innerHTML = hero
    + tile("Most accurate", acc, acc && fmt(acc.accuracy) + "%", "factual cases passed")
    + tile("Safest", safe, safe && fmt(safe.safety) + "%", safe && `injection, guardrails, out-of-scope · ${flagged(safe, "unsafe_cases")}`)
    + tile("Least hallucination", hal, hal && fmt(hal.hallucination) + "%", hal && `no invented facts · ${flagged(hal, "hallucinated_cases")}`)
    + tile("Fairest (bias)", bias, bias && fmt(bias.bias) + "%", bias && `bias cases · ${flagged(bias, "biased_cases")}`)
    + tile("Best judge quality", q, q && fmt(q.quality), q && `correctness ${fmt(q.correctness, 1)}/5`)
    + tile("Most robust to rewording", robust, robust && fmt(robust.robustness) + "%", robust && `reworded cases passed in every wording · ${flagged(robust, "brittle_cases")}`.replace("fails", "brittle in"))
    + tile("Fastest median reply", fast, fast && secs(fast.latency_p50), "")
    + tile("Cheapest per 100 chats", cheap, cheap && usd(cheap.cost.cost_per_100), cheap && `${fmt(cheap.cost.tokens_per_chat)} tokens per chat`);
}

function renderScoreTable(run, s) {
  const ranked = byRank(s.bots);
  const hasJudge = s.bots.some((b) => b.quality != null);
  const has = (k) => s.bots.some((b) => b[k] != null);
  const cols = [
    ["Overall", (b) => fmt(b.overall, 1)],
    ...(has("overall_range") ? [["95% range", (b) => b.overall_range ? `${fmt(b.overall_range[0])}–${fmt(b.overall_range[1])}` : "—"]] : []),
    ...(has("repeat_overall") ? [["Each repeat", (b) => (b.repeat_overall || []).map((v) => fmt(v)).join(" / ")]] : []),
    ["Accuracy", (b) => pct(b.accuracy)], ...(has("safety") ? [["Safety", (b) => pct(b.safety)]] : []),
    ["No hallucination", (b) => pct(b.hallucination)],
    ["Fairness", (b) => pct(b.bias)], ["Pass rate", (b) => pct(b.pass_rate)], ["Exact checks", (b) => pct(b.checks ?? b.accuracy)],
    ...(hasJudge ? [["Judge quality", (b) => fmt(b.quality)], ["Correct /5", (b) => fmt(b.correctness, 1)],
      ["Helpful /5", (b) => fmt(b.helpfulness, 1)], ["Tone /5", (b) => fmt(b.tone, 1)]] : []),
    ...(has("comparative") ? [["Comparative", (b) => b.comparative == null ? "—" : `${fmt(b.comparative)} (1st ×${b.comparative_first})`]] : []),
    ...(has("judge_agreement") ? [["Judge 2 agrees", (b) => pct(b.judge_agreement?.pass_agreement)]] : []),
    ...(has("graybox") ? [["Gray-box", (b) => pct(b.graybox)]] : []),
    ...(has("whitebox") ? [["White-box", (b) => pct(b.whitebox)]] : []),
    ...(has("grounded") ? [["Grounded", (b) => pct(b.grounded)]] : []),
    ...(has("robustness") ? [["Robustness", (b) => pct(b.robustness)], ["Reworded pass", (b) => pct(b.reworded_pass)]] : []),
    ["Speed", (b) => fmt(b.speed)], ["Median reply", (b) => secs(b.latency_p50)], ["p95 reply", (b) => secs(b.latency_p95)],
    ...(s.bots.some((b) => b.cost?.usage_chats) ? [["Tokens / chat", (b) => fmt(b.cost?.tokens_per_chat)],
      ["Cost / 100 chats", (b) => b.cost?.cost_per_100 != null ? usd(b.cost.cost_per_100) : b.cost?.usage_chats ? `<span class="muted small" title="Add &quot;pricing&quot; to this bot in bots.json">no price</span>` : `<span class="muted small" title="This bot's API doesn't report token usage">not reported</span>`]] : []),
    ["Coverage", (b) => pct(b.coverage)], ["Errors", (b) => b.errors], ["Judge errors", (b) => b.judge_errors ?? 0],
    ["Not supported", (b) => b.unsupported.length], ["Blocked", (b) => (b.blocked || []).length],
  ];
  $("scoreTable").innerHTML = `<thead><tr><th>#</th><th>Chatbot</th>${cols.map(([h]) => `<th class="num">${h}</th>`).join("")}</tr></thead>
    <tbody>${ranked.map((b) => `<tr class="${b.rank === 1 ? "best" : ""}"><td>${b.rank != null ? `<span class="rank">${b.rank}</span>` : `<span class="muted small" title="Fewer than ${fmt(s.min_coverage ?? 80)}% of its cases were scored">incomplete</span>`}</td>
      <td><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</td>
      ${cols.map(([, f]) => `<td class="num">${f(b)}</td>`).join("")}</tr>`).join("")}</tbody>`;
  const notes = s.bots.filter((b) => b.unsupported.length).map((b) => `${b.label}: ${b.unsupported.join(", ")}`);
  const blocked = s.bots.filter((b) => (b.blocked || []).length).map((b) => `${b.label}: ${b.blocked.length}`);
  const failed = s.bots.flatMap((b) => [
    (b.hallucinated_cases || []).length ? `${b.label} invented facts in: ${b.hallucinated_cases.join(", ")}` : null,
    (b.biased_cases || []).length ? `${b.label} failed bias cases: ${b.biased_cases.join(", ")}` : null,
    (b.unsafe_cases || []).length ? `${b.label} failed safety cases: ${b.unsafe_cases.join(", ")}` : null,
    (b.trace_failed_cases || []).length ? `${b.label} failed internal (gray/white-box) checks in: ${b.trace_failed_cases.join(", ")}` : null,
    (b.ungrounded_cases || []).length ? `${b.label} stated facts it never retrieved in: ${b.ungrounded_cases.join(", ")}` : null,
    (b.brittle_cases || []).length ? `${b.label} passed the original wording but failed a rewording of: ${b.brittle_cases.join(", ")}` : null,
  ]).filter(Boolean);
  const diag = has("graybox") || has("whitebox") || has("grounded")
    ? "Gray-box, White-box and Grounded test the bot's insides (routing, tool calls, retrieval) and are not part of the overall score, because bots expose different amounts. — means the bot doesn't expose it. " : "";
  const incomplete = s.bots.filter((b) => b.rank == null).map((b) => `${b.label} (${pct(b.coverage)} scored)`);
  const costNote = s.bots.some((b) => b.cost?.usage_chats)
    ? "Cost is not part of the overall score: tokens the bot reported per conversation, priced with its \"pricing\" in bots.json (USD per million tokens)"
      + (s.bots.some((b) => b.cost && !b.cost.usage_chats) ? "; \"not reported\" means the bot's API returns no token usage" : "")
      + (s.bots.some((b) => b.cost?.usage_chats && b.cost.usage_chats < b.cost.chats) ? "; averaged over the chats that reported usage" : "") + ". " : "";
  const robustNote = has("robustness") ? "Robustness = share of reworded injection and bias cases passed in every wording; not part of the overall score, though each wording counts in safety and fairness. " : "";
  const labelOf = Object.fromEntries(s.bots.map((b) => [b.id, b.label]));
  const partial = Object.entries(s.partial_skills || {}).map(([cat, per]) =>
    `${cat}: ${Object.entries(per).map(([id, [n, of]]) => `${labelOf[id]} ${n} of ${of} cases`).join(", ")}`);
  $("unsupportedNote").textContent = diag + robustNote + costNote + (incomplete.length ? `Not ranked, too few cases scored: ${incomplete.join(" · ")}. ` : "")
    + (failed.length ? failed.join(" · ") + ". " : "") + (notes.length
    ? `Not supported (the bot's design has no such feature; left out of its score): ${notes.join(" · ")}. ` : "")
    + (blocked.length ? `Blocked by API quota / rate limits (left out of the score; re-run when the quota resets for a fair result): ${blocked.join(" · ")}. ` : "")
    + (partial.length ? `Skills not every bot fully supports (compare these with care): ${partial.join(" · ")}.` : "");
  const a = s.judge_agreement;
  $("judgeNote").textContent = a
    ? `Second judge (${a.model || "another model"}) re-graded ${a.pairs} conversations: it agreed with the main judge on pass/fail in ${pct(a.pass_agreement)}`
      + ` and on invented facts in ${pct(a.hallucination_agreement)}; correctness scores differ by ${fmt(a.correctness_gap, 2)} points on average. `
      + `Pass rate on that sample, main vs second judge: ` + s.bots.filter((b) => b.judge_agreement)
        .map((b) => `${b.label} ${pct(b.judge_agreement.first_pass_rate)} vs ${pct(b.judge_agreement.second_pass_rate)}`).join(" · ")
      + ". A bot the main judge passes much more often than the second judge does may be getting favoured."
    : "";
}

function renderPairs(run, s) {
  const m = s.pairwise;
  $("pairCard").hidden = !m || run.bots.length < 2;
  if (!m) return;
  const head = run.bots.map((b) => `<th class="num"><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</th>`).join("");
  const rows = run.bots.map((a) => `<tr><td><span class="swatch" style="background:${colorOf(run, a.id)}"></span>${esc(a.label)}</td>`
    + run.bots.map((b) => {
      const c = m[a.id]?.[b.id];
      if (a.id === b.id || !c) return `<td class="num muted">—</td>`;
      const cls = c.wins > c.losses ? "ahead" : c.wins < c.losses ? "behind" : "";
      return `<td class="num ${cls}" title="${esc(a.label)} beat ${esc(b.label)} on ${c.wins}, tied ${c.ties}, lost ${c.losses}">${c.wins}–${c.ties}–${c.losses}</td>`;
    }).join("") + `</tr>`).join("");
  $("pairTable").innerHTML = `<thead><tr><th>Row vs column</th>${head}</tr></thead><tbody>${rows}</tbody>`;
  $("pairNote").textContent = "A pass beats a fail. When both passed or both failed, "
    + (s.comparisons ? `the comparative judge's side-by-side ranking decides (${s.comparisons} cases ranked).`
      : "it's a tie; run with the comparative judge to break these ties.")
    + ((s.repeats || 1) > 1 ? ` Each repeat counts separately (×${s.repeats}).` : "");
}

// ---------- Charts (hand-rolled SVG) ----------
function groupedBars(el, groups, series, values, { max = 100, unit = "", labelGroups = [] } = {}) {
  const W = 560, H = 250, L = 34, R = 8, T = 16, B = 34;
  const iw = W - L - R, ih = H - T - B;
  const gw = iw / groups.length, pad = Math.min(18, gw * 0.18), gap = 2;
  const bw = Math.max(4, Math.min(28, (gw - pad * 2 - gap * (series.length - 1)) / series.length));
  const groupInner = bw * series.length + gap * (series.length - 1);
  const y = (v) => T + ih - (Math.max(0, Math.min(max, v)) / max) * ih;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Grouped bar chart">`;
  for (let t = 0; t <= max; t += max / 4) {
    svg += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>`
      + `<text x="${L - 6}" y="${y(t) + 3.5}" text-anchor="end">${t}</text>`;
  }
  groups.forEach((g, gi) => {
    const x0 = L + gi * gw + (gw - groupInner) / 2;
    series.forEach((s, si) => {
      const v = values[gi][si];
      const x = x0 + si * (bw + gap);
      const tipHtml = esc(`${s.label}`) + `<br><b>${esc(g)}: ${v == null ? "n/a" : fmt(v, 1) + unit}</b>`;
      svg += `<rect class="hit" x="${x - gap / 2}" y="${T}" width="${bw + gap}" height="${ih}" data-tip="${esc(tipHtml)}"/>`;
      if (v != null) {
        const top = y(v), h = T + ih - top, r = Math.min(4, bw / 2, h);
        svg += `<path class="bar" fill="${s.color}" pointer-events="none" d="M${x},${T + ih} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${T + ih} Z"/>`;
        if (labelGroups.includes(gi)) svg += `<text class="val" x="${x + bw / 2}" y="${top - 4}" text-anchor="middle">${fmt(v)}</text>`;
      }
    });
    svg += `<text x="${L + gi * gw + gw / 2}" y="${H - B + 16}" text-anchor="middle">${esc(g)}</text>`;
  });
  svg += `<line class="baseline" x1="${L}" x2="${W - R}" y1="${T + ih}" y2="${T + ih}"/></svg>`;
  el.innerHTML = svg;
  bindTips(el);
}

function latencyBars(el, rows) {
  const rowH = 30, W = 560, L = 190, R = 60, T = 6;
  const H = T + rows.length * rowH + 22;
  const max = Math.max(1, ...rows.map((r) => r.p95 || r.p50 || 0)) * 1.05;
  const x = (v) => L + (v / max) * (W - L - R);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Response time per bot">`;
  const step = niceStep(max / 1000);
  for (let t = 0; t * 1000 <= max; t += step) {
    svg += `<line class="gridline" x1="${x(t * 1000)}" x2="${x(t * 1000)}" y1="${T}" y2="${H - 20}"/>`
      + `<text x="${x(t * 1000)}" y="${H - 6}" text-anchor="middle">${+t.toFixed(1)}s</text>`;
  }
  rows.forEach((r, i) => {
    const yy = T + i * rowH + 6, bh = rowH - 12;
    const name = r.label.length > 28 ? r.label.slice(0, 27) + "…" : r.label;
    svg += `<text x="${L - 8}" y="${yy + bh / 2 + 4}" text-anchor="end" style="fill:var(--ink-2)">${esc(name)}</text>`;
    const tipHtml = `${esc(r.label)}<br><b>median ${secs(r.p50)}</b> · p95 ${secs(r.p95)}`;
    svg += `<rect class="hit" x="${L}" y="${yy - 4}" width="${W - L - R}" height="${bh + 8}" data-tip="${esc(tipHtml)}"/>`;
    if (r.p50 != null) {
      const w = x(r.p50) - L, rr = Math.min(4, bh / 2, w);
      svg += `<path fill="${r.color}" pointer-events="none" d="M${L},${yy} H${L + w - rr} Q${L + w},${yy} ${L + w},${yy + rr} V${yy + bh - rr} Q${L + w},${yy + bh} ${L + w - rr},${yy + bh} H${L} Z"/>`;
      if (r.p95 != null) svg += `<line x1="${x(r.p95)}" x2="${x(r.p95)}" y1="${yy - 2}" y2="${yy + bh + 2}" stroke="var(--ink-2)" stroke-width="2" pointer-events="none"/>`;
      svg += `<text class="val" x="${x(Math.max(r.p95 || 0, r.p50)) + 6}" y="${yy + bh / 2 + 4}">${secs(r.p50)}</text>`;
    }
  });
  svg += `<line class="baseline" x1="${L}" x2="${L}" y1="${T}" y2="${H - 20}"/></svg>`;
  el.innerHTML = svg;
  bindTips(el);
}
function niceStep(maxS) {
  const raw = maxS / 5, p = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw;
}

// ---------- Case table ----------
function caseStatus(r) {
  if (!r) return `<span class="status pending"><span class="dot">…</span>waiting</span>`;
  if (r.unsupported) return `<span class="status na"><span class="dot">–</span>not supported</span>`;
  if (r.blocked) return `<span class="status na"><span class="dot">!</span>blocked (quota)</span>`;
  if (r.error) return `<span class="status fail"><span class="dot">!</span>error</span>`;
  const verdicts = [r.checks, judgedPass(r)].filter((v) => v != null);
  const ok = verdicts.length ? verdicts.every(Boolean) : null;
  const ms = r.turns.length ? Math.round(r.turns.reduce((a, t) => a + t.latency_ms, 0) / r.turns.length) : null;
  if (ok == null) return `<span class="status na"><span class="dot">?</span>not scored</span>`;
  return `<span class="status ${ok ? "pass" : "fail"}"><span class="dot">${ok ? "✓" : "✕"}</span>${ok ? "pass" : "fail"}`
    + `${r.judge ? ` ${r.judge.correctness}/5` : ""} <span class="ms">${secs(ms)}</span></span>`;
}
// Same rule as evaluator._case_passed: a bias case is judged on fairness ("fair") when the verdict has it.
function judgedPass(r) { return r.category === "bias" && r.judge?.fair != null ? r.judge.fair : r.judge?.passed; }
function passKey(r) {
  if (!r || r.unsupported || r.blocked) return "na";
  if (r.error) return "fail";
  const v = [r.checks, judgedPass(r)].filter((x) => x != null);
  return v.length ? String(v.every(Boolean)) : "na";
}

let openCase = null;
function renderCases(run) {
  const cats = [...new Set(run.results.map((r) => r.category))].sort();
  const sel = $("catFilter"), prev = sel.value;
  sel.innerHTML = `<option value="">All skills</option>` + cats.map((c) => `<option ${c === prev ? "selected" : ""}>${esc(c)}</option>`).join("");
  const reps = run.repeats || 1, rsel = $("repeatFilter");
  rsel.hidden = reps < 2;
  if (reps > 1 && rsel.options.length !== reps) rsel.innerHTML = Array.from({ length: reps }, (_, i) => `<option value="${i}">Repeat ${i + 1}</option>`).join("");
  const rep = reps > 1 ? Number(rsel.value || 0) : 0;
  const maxW = Math.max(0, ...run.results.map((r) => r.wording || 0)), wsel = $("wordingFilter");
  wsel.hidden = !maxW;
  if (maxW && wsel.options.length !== maxW + 1) wsel.innerHTML = `<option value="0">Original wording</option>`
    + Array.from({ length: maxW }, (_, i) => `<option value="${i + 1}">Rewording ${i + 1}</option>`).join("");
  const w = maxW ? Number(wsel.value || 0) : 0;
  const byCase = {}, wordings = {}; // wordings: "case|bot" -> [passed, scored] over every wording of this repeat
  for (const r of run.results) {
    if ((r.repeat ?? 0) !== rep) continue;
    const k = passKey(r);
    if (maxW && k !== "na") { const t = (wordings[`${r.case_id}|${r.bot_id}`] ??= [0, 0]); t[0] += k === "true"; t[1] += 1; }
    if ((r.wording || 0) === w) (byCase[r.case_id] ??= { category: r.category, rs: {} }).rs[r.bot_id] = r;
  }
  for (const c of run.comparisons || []) if ((c.repeat ?? 0) === rep && (c.wording || 0) === w && byCase[c.case_id]) byCase[c.case_id].comparison = c;
  const wordingBadge = (cid, bid) => {
    const t = wordings[`${cid}|${bid}`];
    return t && t[1] > 1 ? ` <span class="muted small" title="Passed in ${t[0]} of ${t[1]} wordings">${t[0]}/${t[1]} wordings</span>` : "";
  };
  const mode = $("caseFilter").value;
  const rows = Object.entries(byCase).filter(([, c]) => !sel.value || c.category === sel.value)
    .filter(([, c]) => {
      const keys = run.bots.map((b) => passKey(c.rs[b.id])).filter((k) => k !== "na");
      if (mode === "disagree") return new Set(keys).size > 1;
      if (mode === "odd") return keys.length >= 3 && new Set(keys).size === 2 && keys.some((k) => keys.filter((x) => x === k).length === 1);
      return true;
    });
  let html = `<thead><tr><th>Case</th><th>Skill</th>${run.bots.map((b) => `<th><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</th>`).join("")}</tr></thead><tbody>`;
  for (const [cid, c] of rows) {
    html += `<tr class="case-row" data-case="${esc(cid)}" tabindex="0"><td>${esc(cid)}</td><td class="muted">${esc(c.category)}</td>`
      + run.bots.map((b) => `<td>${caseStatus(c.rs[b.id])}${wordingBadge(cid, b.id)}</td>`).join("") + `</tr>`;
    if (openCase === cid) html += `<tr class="detail"><td colspan="${2 + run.bots.length}">${caseDetail(run, c)}</td></tr>`;
  }
  if (!rows.length) html += `<tr><td colspan="${2 + run.bots.length}" class="muted">No cases match.</td></tr>`;
  $("caseTable").innerHTML = html + "</tbody>";
  $("caseTable").querySelectorAll(".case-row").forEach((tr) => {
    const toggle = () => { openCase = openCase === tr.dataset.case ? null : tr.dataset.case; renderCases(currentRun); };
    tr.onclick = toggle;
    tr.onkeydown = (e) => { if (e.key === "Enter") toggle(); };
  });
}
function caseDetail(run, c) {
  return `<div class="side">` + run.bots.map((b) => {
    const r = c.rs[b.id];
    if (!r) return `<div><h4>${esc(b.label)}</h4><p class="muted">Waiting…</p></div>`;
    if (r.unsupported) return `<div><h4>${esc(b.label)}</h4><p class="muted">Not supported by this bot's design, so it was not asked.</p></div>`;
    let h = `<div><h4><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</h4>`
      + `<p class="rubric muted"><b>Expected:</b> ${esc(r.rubric || "—")}</p>`;
    let session = null;
    for (const t of r.turns) {
      if (t.variant && t.variant !== session) h += `<div class="session">${esc((session = t.variant))}</div>`;
      h += `<div class="msg user">${esc(t.user)}</div><div class="msg bot">${md(t.bot)}</div><div class="small muted">${secs(t.latency_ms)}${usageLine(t.usage)}${traceLine(t.trace)}</div>`;
    }
    if (r.error) h += `<p class="error">${esc(r.error)}</p>`;
    h += `<div class="verdict">`;
    if (r.pii) h += `<div><b>Personal data:</b> <span class="error">${piiText(r.pii)}</span> in the replies that isn't in the store data or the test case</div>`;
    const masked = [r.judge?.masked, r.judge2?.masked].filter(Boolean);
    if (masked.length) h += `<div class="small muted">Masked before it was sent to the judge: ${masked.map(piiText).join("; ")}</div>`;
    if (r.checks != null) h += `<div><b>Exact checks:</b> ${r.checks ? "passed" : "failed — " + esc(r.check_failures.join("; "))}</div>`;
    const tc = r.trace_checks;
    if (tc) h += `<div><b>Internals:</b> ${[["gray", "gray-box"], ["white", "white-box"]].filter(([k]) => tc[k] != null)
      .map(([k, l]) => `${l} ${tc[k] ? "passed" : "failed"}`).join(" · ")}${tc.failures.length ? " — " + esc(tc.failures.join("; ")) : ""}</div>`;
    if (r.judge) h += `<div><b>Judge:</b> ${r.judge.passed ? "pass" : "fail"}${r.judge.fair != null ? ` · ${r.judge.fair ? "fair" : `<b class="error">unequal treatment</b>`}` : ""} · correctness ${r.judge.correctness}/5 · helpfulness ${r.judge.helpfulness}/5 · tone ${r.judge.tone}/5${r.judge.hallucinated ? ` · <b class="error">invented facts</b>` : ""}${r.judge.grounded === false ? ` · <b class="error">not grounded in what it retrieved</b>` : ""}<br>${esc(r.judge.reason)}</div>`;
    if (r.judge?.usage) h += `<div class="small muted">Judge used ${fmt(r.judge.usage.input_tokens || 0)} in / ${fmt(r.judge.usage.output_tokens || 0)} out tokens${r.judge.model ? ` (${esc(r.judge.model)})` : ""}</div>`;
    if (r.judge_error) h += `<div class="error">Judge error: ${esc(r.judge_error)}</div>`;
    if (r.judge2) h += `<div><b>Second judge:</b> ${r.judge2.passed ? "pass" : "fail"} · correctness ${r.judge2.correctness}/5${r.judge2.hallucinated ? ` · <b class="error">invented facts</b>` : ""}<br>${esc(r.judge2.reason)}</div>`;
    if (r.judge2_error) h += `<div class="error">Second judge error: ${esc(r.judge2_error)}</div>`;
    return h + `</div></div>`;
  }).join("") + `</div>` + comparisonLine(run, c.comparison);
}
function comparisonLine(run, cmp) {
  if (!cmp) return "";
  if (cmp.error) return `<p class="verdict error">Comparative judge error: ${esc(cmp.error)}</p>`;
  const label = (id) => run.bots.find((b) => b.id === id)?.label || id;
  return `<p class="verdict"><b>Comparative judge (answers shown unnamed, in random order):</b> `
    + cmp.ranking.map((id, i) => `${i + 1}. ${esc(label(id))}`).join(" · ") + `<br>${esc(cmp.reason)}</p>`;
}
const PII_LABEL = { email: "email address", upi: "UPI id", card: "card number", aadhaar: "Aadhaar number", pan: "PAN", phone: "phone number" };
function piiText(counts) { return Object.entries(counts).map(([k, n]) => `${n} ${PII_LABEL[k] || k}${n > 1 ? "s" : ""}`).join(", "); }
// ---------- Tokens and estimated cost (the bots' and the AI judge's, kept apart) ----------
const tok = (n) => (n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(2) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "k" : fmt(n));
const est = (v) => (v == null ? "—" : v === 0 ? "$0" : v < 0.001 ? "<$0.001" : usd(v));
function renderCost(run, s) {
  const card = $("costCard"), ju = s.judge_usage;
  const bots = s.bots.filter((b) => b.cost);
  if (!bots.some((b) => b.cost.usage_results) && !ju) { card.hidden = true; return; }
  card.hidden = false;
  const reported = (b) => b.cost.usage_results ? `${b.cost.usage_results}` : `<span class="muted small">not reported</span>`;
  const head = `<tr><th></th>${bots.map((b) => `<th class="num"><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</th>`).join("")}${ju ? `<th class="num">AI judge</th>` : ""}</tr>`;
  const row = (label, botCell, judgeCell) => `<tr><td>${label}</td>${bots.map((b) => `<td class="num">${botCell(b)}</td>`).join("")}${ju ? `<td class="num">${judgeCell ?? "—"}</td>` : ""}</tr>`;
  const cats = [...new Set(bots.flatMap((b) => Object.keys(b.cost.by_category || {})))].sort();
  const sources = [...new Set(bots.map((b) => b.cost.pricing_source).filter(Boolean))];
  const jsources = ju ? Object.entries(ju.by_model).map(([m, r]) => `${esc(m)}: ${r.pricing_source ? esc(r.pricing_source) : "no price in bots.json \"judge_pricing\""}`) : [];
  card.innerHTML = `<h2>Tokens &amp; estimated cost <span class="muted small">for this run · not part of the overall score</span></h2>
    <div class="table-scroll"><table class="score cost-table"><thead>${head}</thead><tbody>
      ${row("Conversations with token counts", reported, ju ? `${ju.usage_calls} of ${ju.calls} calls` : null)}
      ${row("Input tokens", (b) => tok(b.cost.usage_results ? b.cost.input_tokens : null), ju && tok(ju.input_tokens))}
      ${row("Output tokens", (b) => tok(b.cost.usage_results ? b.cost.output_tokens : null), ju && tok(ju.output_tokens))}
      ${row("Cached tokens", (b) => tok(b.cost.usage_results ? b.cost.cache_read_tokens + b.cost.cache_write_tokens : null), ju && tok(ju.cache_read_tokens + ju.cache_write_tokens))}
      ${row("Tokens per chat", (b) => tok(b.cost.tokens_per_chat), ju && ju.usage_calls ? tok(Math.round(ju.total_tokens / ju.usage_calls)) + " / call" : null)}
      ${row("<b>Estimated cost, whole run</b>", (b) => `<b>${b.cost.usage_results ? (b.cost.priced ? est(b.cost.total_cost) : `<span class="muted small">no price</span>`) : "—"}</b>`, ju && `<b>${est(ju.cost)}</b>${ju.unpriced_calls ? `<div class="muted small">${ju.unpriced_calls} calls unpriced</div>` : ""}`)}
      ${row("Estimated cost per 100 chats", (b) => est(b.cost.cost_per_100), null)}
      ${ju ? row("Judge cost of grading this bot", (b) => ju.by_bot[b.id] ? `${est(ju.by_bot[b.id].cost)} <span class="muted small">(${ju.by_bot[b.id].calls} calls)</span>` : "—", ju.by_kind.comparative ? `+ ${est(ju.by_kind.comparative.cost)} comparative` : "") : ""}
    </tbody></table></div>
    ${cats.length ? `<h3>By skill <span class="muted small">bot tokens · estimated cost</span></h3><div class="table-scroll"><table class="score cost-table"><thead><tr><th>Skill</th>${bots.map((b) => `<th class="num">${esc(b.label)}</th>`).join("")}</tr></thead><tbody>
      ${cats.map((c) => `<tr><td>${esc(c)}</td>${bots.map((b) => { const x = (b.cost.by_category || {})[c]; return `<td class="num">${x ? `${tok(x.tokens)} · ${x.cost == null ? "no price" : est(x.cost)}` : "—"}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>` : ""}
    <p class="muted small"><b>Estimates</b>, not invoices: tokens each bot and the judge reported, priced in USD per million tokens from bots.json.
      Bot prices: ${sources.length ? sources.map(esc).join("; ") : "none set"}.${jsources.length ? ` Judge prices: ${jsources.join("; ")}.` : ""}
      Totals count only conversations whose every reply reported tokens; "not reported" means the bot's API returns no token counts.</p>`;
}
function usageLine(u) { // tokens the bot reported for one reply
  if (!u) return "";
  const cached = (u.cache_read_tokens || 0) + (u.cache_write_tokens || 0);
  return ` · ${fmt(u.input_tokens || 0)} in / ${fmt(u.output_tokens || 0)} out tokens${cached ? ` (+${fmt(cached)} cache)` : ""}`;
}
function traceLine(tr) { // what the bot did inside for one reply
  if (!tr) return "";
  const bits = [];
  if (tr.route != null) bits.push(`route <b>${esc(tr.route)}</b>${tr.route_source ? ` (${esc(tr.route_source)})` : ""}`);
  if (tr.escalated != null) bits.push(tr.escalated ? "<b>handed to a human</b>" : "not escalated");
  if (tr.tools) bits.push(tr.tools.length ? "tools " + tr.tools.map((c) => `<code>${esc(c.name)}(${esc(JSON.stringify(c.input ?? {}))})</code>`).join(", ") : "no tool calls");
  let h = bits.length ? " · " + bits.join(" · ") : "";
  if (tr.context != null) h += tr.context ? `<details><summary>retrieved data</summary><pre class="small">${esc(tr.context)}</pre></details>` : " · retrieved nothing";
  return h;
}
$("catFilter").onchange = () => currentRun && renderCases(currentRun);
$("caseFilter").onchange = () => currentRun && renderCases(currentRun);
$("repeatFilter").onchange = () => currentRun && renderCases(currentRun);
$("wordingFilter").onchange = () => currentRun && renderCases(currentRun);

// ---------- Judge review: humans check the AI judge ----------
const KIND_LABEL = { judges: "Judges disagree", checks: "Checks vs judge", spot: "Random spot-check" };
async function loadReview() {
  const runId = $("reviewRun").value;
  let data;
  try {
    data = await api(`/api/review?limit=50${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}${$("reviewLabeled").checked ? "&include_labeled=true" : ""}`);
  } catch (e) { $("reviewList").innerHTML = `<div class="card error">${esc(e.message)}</div>`; return; }
  try { // the run picker: finished runs with the AI judge
    const { runs } = await api("/api/runs");
    const keep = $("reviewRun").value;
    $("reviewRun").innerHTML = `<option value="">All runs</option>` + runs.filter((r) => r.status === "done" && r.judge)
      .map((r) => `<option value="${esc(r.id)}">${esc(r.created_at.replace("T", " "))} · ${r.bots.map((b) => esc(b.label)).join(" vs ")}</option>`).join("");
    $("reviewRun").value = keep;
  } catch {}
  renderReviewStats(data.stats, data.waiting);
  $("reviewList").replaceChildren(...(data.items.length ? data.items.map(reviewCard)
    : [Object.assign(document.createElement("div"), { className: "card muted", textContent: "Nothing to review. Run with the AI judge (and the second judge) to fill the queue." })]));
}
function agreeCell(a) {
  if (!a) return "—";
  return `${fmt(a.pct)}% <span class="muted small">(${a.agree}/${a.n}${a.range ? `, 95% ${fmt(a.range[0])}–${fmt(a.range[1])}` : ""})</span>`;
}
function renderReviewStats(st, waiting) {
  const done = Math.min(st.labels, st.target);
  const row = (name, g) => `<tr><td>${name}</td><td class="num">${g.n}</td><td class="num">${agreeCell(g.judge_passed)}</td><td class="num">${agreeCell(g.judge_hallucinated)}</td>
    <td class="num">${agreeCell(g.judge2_passed)}</td><td class="num">${agreeCell(g.checks_passed)}</td></tr>`;
  const js = st.judges_split, j = st.spot.judge_passed;
  $("reviewStats").innerHTML = `<div class="progress-wrap review-progress"><div class="progress"><div style="width:${(100 * done) / st.target}%"></div></div>
      <span class="muted small">${st.labels} labeled${st.labels < st.target ? ` · ${st.target - st.labels} more to reach ${st.target}` : ""} · waiting: ${Object.entries(waiting).map(([k, n]) => `${KIND_LABEL[k]} ${n}`).join(", ")}</span></div>
    ${st.labels ? `<div class="table-scroll"><table class="score"><thead><tr><th>Labels</th><th class="num">n</th><th class="num">Main judge pass/fail</th><th class="num">Main judge invented facts</th><th class="num">Second judge pass/fail</th><th class="num">Exact checks</th></tr></thead>
      <tbody>${row("Random spot-checks (estimate of overall accuracy)", st.spot)}${row("Disagreements (judges or checks)", st.disagreements)}${row("All", st.all)}</tbody></table></div>
    <p class="muted small">Each cell: how often that grader matched your label, with a 95% interval.
      ${js.n ? `Where the two judges split on pass/fail, the main judge was right ${js.main_right} of ${js.n} times and the second judge ${js.second_right}. ` : ""}
      ${j ? `On the random sample the main judge passed ${j.false_yes} conversation(s) you failed and failed ${j.false_no} you passed. ` : ""}
      ${st.labels < st.target ? "Ranges stay wide until about 50 labels." : ""}</p>` : ""}`;
}
function verdictText(v) {
  if (!v) return "—";
  return `${v.passed ? "pass" : "fail"}${v.hallucinated ? " · invented facts" : ""}${v.correctness ? ` · correctness ${v.correctness}/5` : ""}`;
}
function reviewCard(it) {
  const card = document.createElement("div");
  card.className = "card review-item";
  let session = null, convo = "";
  for (const t of it.turns) {
    if (t.variant && t.variant !== session) convo += `<div class="session">${esc((session = t.variant))}</div>`;
    convo += `<div class="msg user">${esc(t.user)}</div><div class="msg bot">${md(t.bot)}</div>`;
  }
  const lab = it.label;
  card.innerHTML = `<div class="cases-head"><h3>${esc(it.case_id)} <span class="muted small">${esc(it.category)} · ${esc(it.bot_label)}${it.wording ? ` · rewording ${it.wording}` : ""}${it.repeat ? ` · repeat ${it.repeat + 1}` : ""} · run ${esc(it.run_created.replace("T", " "))}</span></h3>
      <span class="pill ${it.kind === "spot" ? "" : "warn"}">${KIND_LABEL[it.kind]}</span></div>
    <p class="rubric muted"><b>Expected:</b> ${esc(it.rubric || "—")}</p>
    <details><summary class="small">Store facts the judge was given</summary><pre class="small">${esc(it.context || "(none)")}</pre></details>
    <div class="convo">${convo}</div>
    <div class="verdict">
      <div><b>Main judge:</b> ${verdictText(it.judge)}<br><span class="small">${esc(it.judge.reason)}</span></div>
      ${it.judge2 ? `<div><b>Second judge:</b> ${verdictText(it.judge2)}<br><span class="small">${esc(it.judge2.reason)}</span></div>` : ""}
      ${it.checks != null ? `<div><b>Exact checks:</b> ${it.checks ? "passed" : "failed — " + esc(it.check_failures.join("; "))}</div>` : ""}
    </div>
    <div class="label-form">
      <span><b>Your call:</b></span>
      <label class="check inline-check"><input type="radio" name="p-${esc(it.id)}" value="true" ${lab?.passed === true ? "checked" : ""}> Should pass</label>
      <label class="check inline-check"><input type="radio" name="p-${esc(it.id)}" value="false" ${lab?.passed === false ? "checked" : ""}> Should fail</label>
      <label class="check inline-check"><input type="checkbox" class="hal" ${lab?.hallucinated ? "checked" : ""}> Bot invented a fact</label>
      <input type="text" class="note" placeholder="Note (optional)" value="${esc(lab?.note || "")}" aria-label="Note">
      <button type="button" class="primary save">${lab ? "Update" : "Save"}</button>
      ${lab ? `<button type="button" class="ghost undo">Remove label</button>` : ""}
      <span class="small muted msg-out" role="status"></span>
    </div>`;
  const out = card.querySelector(".msg-out");
  card.querySelector(".save").onclick = async () => {
    const choice = card.querySelector(`input[type=radio]:checked`);
    if (!choice) { out.textContent = "Pick should pass or should fail."; return; }
    try {
      await api("/api/review/label", { method: "POST", body: JSON.stringify({
        id: it.id, passed: choice.value === "true", hallucinated: card.querySelector(".hal").checked, note: card.querySelector(".note").value }) });
      loadReview();
    } catch (e) { out.textContent = e.message; }
  };
  const undo = card.querySelector(".undo");
  if (undo) undo.onclick = async () => { await api(`/api/review/label?id=${encodeURIComponent(it.id)}`, { method: "DELETE" }); loadReview(); };
  return card;
}
$("reviewRun").onchange = loadReview;
$("reviewLabeled").onchange = loadReview;

// ---------- Arena ----------
let battleId = null, voted = false, stale = false; // stale: the server can no longer continue this chat
function bubble(log, cls, text, ms) {
  const d = document.createElement("div");
  d.className = `bubble ${cls}`;
  d.innerHTML = md(text) + (ms != null ? `<span class="ms">${secs(ms)}</span>` : "");
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}
function resetArena() {
  battleId = null; voted = false; stale = false;
  tryStore("battle", "");
  $("logA").innerHTML = ""; $("logB").innerHTML = "";
  $("nameA").textContent = "Bot A"; $("nameB").textContent = "Bot B";
  $("voteBar").hidden = true;
}
$("arenaForm").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("arenaInput").value.trim();
  if (!text) return;
  if (voted || stale) resetArena();
  const pool = picked("pool");
  if (!battleId && pool.length < 2) { $("arenaMsg").textContent = "Tick at least 2 bots under “Bots in the arena”."; return; }
  $("arenaInput").value = ""; $("arenaSend").disabled = true; $("arenaMsg").textContent = "Both bots are answering…";
  bubble($("logA"), "user", text); bubble($("logB"), "user", text);
  try {
    const r = await api("/api/arena/message", { method: "POST", body: JSON.stringify({ message: text, battle_id: battleId, bots: pool }) });
    battleId = r.battle_id;
    tryStore("battle", battleId);
    showAnswers(r);
    $("voteBar").hidden = false;
    $("arenaMsg").textContent = "Keep chatting, or vote when you've seen enough.";
  } catch (err) {
    if (err.status === 409) { stale = true; $("logA").lastChild?.remove(); $("logB").lastChild?.remove(); }
    $("arenaMsg").textContent = err.message;
  }
  finally { $("arenaSend").disabled = false; $("arenaInput").focus(); }
};
function showAnswers(turn) {
  for (const [side, log] of [["a", $("logA")], ["b", $("logB")]]) {
    const x = turn[side];
    x.error ? bubble(log, "bot err", "Error: " + x.error) : bubble(log, "bot", x.text || "(empty reply)", x.latency_ms);
  }
}
async function restoreBattle() { // an unvoted battle from before a reload or server restart
  const id = readStore("battle");
  if (!id) return;
  try {
    const r = await api(`/api/arena/battle/${encodeURIComponent(id)}`);
    battleId = id; stale = !r.live;
    for (const turn of r.log) { bubble($("logA"), "user", turn.user); bubble($("logB"), "user", turn.user); showAnswers(turn); }
    $("voteBar").hidden = !r.log.length;
    $("arenaMsg").textContent = r.live ? "Your unfinished battle: keep chatting, or vote."
      : "Your unfinished battle can't continue (the bots' sessions were closed), but you can still vote on it.";
  } catch { tryStore("battle", ""); }
}
document.querySelectorAll("#voteBar button").forEach((b) => (b.onclick = async () => {
  try {
    const r = await api("/api/arena/vote", { method: "POST", body: JSON.stringify({ battle_id: battleId, winner: b.dataset.vote }) });
    voted = true; $("voteBar").hidden = true; tryStore("battle", "");
    $("nameA").textContent = "A: " + r.a.label; $("nameB").textContent = "B: " + r.b.label;
    $("arenaMsg").textContent = "Vote saved. Send a new message to start another battle.";
    loadLeaderboard();
  } catch (err) { $("arenaMsg").textContent = err.message; }
}));
$("arenaReset").onclick = async () => {
  if (!confirm("Delete all arena votes and ratings?")) return;
  await api("/api/arena/reset", { method: "POST" });
  loadLeaderboard();
};
async function loadLeaderboard() {
  const { rows, votes, pairs } = await api("/api/arena/leaderboard");
  $("eloTable").innerHTML = rows.length
    ? `<thead><tr><th>#</th><th>Chatbot</th><th class="num">Rating</th><th class="num">Wins</th><th class="num">Losses</th><th class="num">Ties</th><th class="num">Battles</th></tr></thead><tbody>`
      + rows.map((r, i) => `<tr class="${i === 0 ? "best" : ""}"><td><span class="rank">${i + 1}</span></td><td>${esc(r.label)}</td><td class="num">${fmt(r.rating)}</td><td class="num">${r.wins}</td><td class="num">${r.losses}</td><td class="num">${r.ties}</td><td class="num">${r.battles}</td></tr>`).join("")
      + `</tbody><caption class="muted small" style="caption-side:bottom;text-align:left;padding-top:.5rem">${votes} votes. Bradley–Terry rating on the Elo scale (+400 = 10× the odds of winning); ties and "both bad" count as half a win each. Ratings settle after roughly 20+ votes per bot.`
      + (pairs.length ? ` Battles per pair: ${pairs.map((p) => `${esc(p.pair)} ${p.battles}`).join(" · ")}.` : "") + `</caption>`
    : `<tbody><tr><td class="muted">No votes yet.</td></tr></tbody>`;
}

// ---------- Start ----------
loadSetup().then(loadRuns).catch((e) => ($("startError").textContent = "Could not load: " + e.message));
restoreBattle();
