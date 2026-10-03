const $ = (id) => document.getElementById(id);
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
const METRICS = [
  ["overall", "Overall"], ["accuracy", "Accuracy"], ["hallucination", "No hallucination"],
  ["bias", "Fairness (bias)"], ["quality", "Judge quality"], ["speed", "Speed"],
];
let bots = [], suites = [], currentRunId = null, pollTimer = null, currentRun = null;

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
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}
const fmt = (v, d = 0) => (v == null ? "—" : Number(v).toFixed(d));
const pct = (v) => (v == null ? "—" : fmt(v) + "%");
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
  [{ bots }, { suites }] = await Promise.all([api("/api/bots"), api("/api/suites")]);
  let picked = [];
  try { picked = JSON.parse(readStore("picked") || "[]"); } catch {}
  if (!picked.length) picked = bots.slice(0, 2).map((b) => b.id);
  $("botList").replaceChildren(...bots.map((b) => botRow(b, picked.includes(b.id), "pick")));
  $("arenaPool").replaceChildren(...bots.map((b) => botRow(b, picked.includes(b.id), "pool")));
  $("botList").addEventListener("change", updatePickCount);
  updatePickCount();
  $("suiteSelect").innerHTML = suites.map((s) => `<option value="${esc(s.id)}">${esc(s.name)} (${s.cases} cases)</option>`).join("");
  $("suiteSelect").onchange = showSuiteInfo;
  showSuiteInfo();
}
function picked(name) { return [...document.querySelectorAll(`input[name=${name}]:checked`)].map((i) => i.value); }
function updatePickCount() {
  const n = picked("pick").length;
  $("pickCount").textContent = `(${n} selected)`;
  $("startBtn").disabled = n < 2 || n > 4;
  tryStore("picked", JSON.stringify(picked("pick")));
}
function showSuiteInfo() {
  const s = suites.find((x) => x.id === $("suiteSelect").value);
  $("suiteInfo").textContent = s ? `${s.description} Skills: ${s.categories.join(", ")}.` : "";
}

$("startBtn").onclick = async () => {
  $("startError").textContent = "";
  $("startBtn").disabled = true;
  try {
    const { id } = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({ bots: picked("pick"), suite: $("suiteSelect").value, judge: $("judgeToggle").checked }),
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
    row.innerHTML = `<span><b>${r.bots.map((b) => esc(b.label)).join(" vs ")}</b><br>
      <span class="muted small">${esc(r.suite_name)} · ${esc(r.created_at.replace("T", " "))}${r.judge ? " · AI judge" : ""}</span></span>
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
  else loadRuns();
}

function colorOf(run, botId) { return SERIES[run.bots.findIndex((b) => b.id === botId) % SERIES.length]; }

function renderRun(run) {
  $("resultsEmpty").hidden = true; $("results").hidden = false;
  $("runTitle").textContent = run.bots.map((b) => b.label).join("  vs  ");
  $("runMeta").textContent = `${run.suite_name} · ${run.created_at.replace("T", " ")} · ${run.judge ? "AI judge: " + run.judge_model : "no AI judge (exact checks only)"}`
    + (run.failure ? ` · failed: ${run.failure}` : "");
  const { done, total } = run.progress;
  $("progressWrap").hidden = run.status === "done";
  $("progressBar").style.width = `${(100 * done) / Math.max(total, 1)}%`;
  $("progressText").textContent = run.status === "running" ? `Running… ${done} of ${total} conversations` : run.status;

  const s = run.summary;
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
  } else {
    $("tiles").innerHTML = ""; $("scoreTable").innerHTML = ""; $("unsupportedNote").textContent = "";
    ["chartScores", "chartCats", "chartLatency", "legendScores", "legendCats"].forEach((i) => ($(i).innerHTML = ""));
    if (run.status === "running") $("tiles").innerHTML = `<div class="tile hero"><div class="label">Scores</div><div class="sub">Charts appear when the run finishes. Case results fill in below as they arrive.</div></div>`;
  }
  renderCases(run);
}

function renderLegend(elId, run) {
  $(elId).innerHTML = run.bots.map((b) => `<span><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</span>`).join("");
}

const byRank = (bots) => [...bots].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));

function renderTiles(run, s) {
  const ranked = byRank(s.bots).filter((b) => b.rank != null);
  const w = ranked[0];
  const close = s.winner && s.winner.margin != null && s.winner.margin < 3;
  const hero = w
    ? `<div class="tile hero"><div class="label">${close ? "Too close to call — leader" : "Winner"}</div>
    <div class="value"><span class="swatch" style="background:${colorOf(run, w.id)}"></span>${esc(w.label)}</div>
    <div class="sub">Overall ${fmt(w.overall, 1)} / 100${s.winner.margin != null ? ` · ${fmt(s.winner.margin, 1)} points ahead of ${esc(ranked[1].label)}` : ""}</div></div>`
    : `<div class="tile hero"><div class="label">No winner</div><div class="value">Not enough cases scored</div>
    <div class="sub">A bot is ranked once at least ${fmt(s.min_coverage ?? 80)}% of its cases were scored. Re-run when quotas reset.</div></div>`;
  const best = (k, better = "max") => {
    const vals = s.bots.filter((b) => b[k] != null && b.rank != null);
    if (!vals.length) return null;
    return vals.reduce((a, b) => ((better === "max" ? b[k] > a[k] : b[k] < a[k]) ? b : a));
  };
  const tile = (label, b, val, sub) => b ? `<div class="tile"><div class="label">${label}</div><div class="value">${val}</div>
    <div class="sub"><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}${sub ? " · " + sub : ""}</div></div>` : "";
  const acc = best("accuracy"), hal = best("hallucination"), bias = best("bias"), q = best("quality"), fast = best("latency_p50", "min");
  const flagged = (b, k) => b && b[k]?.length ? `fails ${b[k].length}` : "none failed";
  $("tiles").innerHTML = hero
    + tile("Most accurate", acc, acc && fmt(acc.accuracy) + "%", "factual cases passed")
    + tile("Least hallucination", hal, hal && fmt(hal.hallucination) + "%", hal && `no invented facts · ${flagged(hal, "hallucinated_cases")}`)
    + tile("Fairest (bias)", bias, bias && fmt(bias.bias) + "%", bias && `bias cases · ${flagged(bias, "biased_cases")}`)
    + tile("Best judge quality", q, q && fmt(q.quality), q && `correctness ${fmt(q.correctness, 1)}/5`)
    + tile("Fastest median reply", fast, fast && secs(fast.latency_p50), "");
}

function renderScoreTable(run, s) {
  const ranked = byRank(s.bots);
  const hasJudge = s.bots.some((b) => b.quality != null);
  const cols = [
    ["Overall", (b) => fmt(b.overall, 1)], ["Accuracy", (b) => pct(b.accuracy)], ["No hallucination", (b) => pct(b.hallucination)],
    ["Fairness", (b) => pct(b.bias)], ["Pass rate", (b) => pct(b.pass_rate)], ["Exact checks", (b) => pct(b.checks ?? b.accuracy)],
    ...(hasJudge ? [["Judge quality", (b) => fmt(b.quality)], ["Correct /5", (b) => fmt(b.correctness, 1)],
      ["Helpful /5", (b) => fmt(b.helpfulness, 1)], ["Tone /5", (b) => fmt(b.tone, 1)]] : []),
    ["Median reply", (b) => secs(b.latency_p50)], ["p95 reply", (b) => secs(b.latency_p95)],
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
  ]).filter(Boolean);
  const incomplete = s.bots.filter((b) => b.rank == null).map((b) => `${b.label} (${pct(b.coverage)} scored)`);
  $("unsupportedNote").textContent = (incomplete.length ? `Not ranked, too few cases scored: ${incomplete.join(" · ")}. ` : "")
    + (failed.length ? failed.join(" · ") + ". " : "") + (notes.length
    ? `Not supported (the bot's design has no such feature; left out of its score): ${notes.join(" · ")}. ` : "")
    + (blocked.length ? `Blocked by API quota / rate limits (left out of the score; re-run when the quota resets for a fair result): ${blocked.join(" · ")}.` : "");
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
  const verdicts = [r.checks, r.judge?.passed].filter((v) => v != null);
  const ok = verdicts.length ? verdicts.every(Boolean) : null;
  const ms = r.turns.length ? Math.round(r.turns.reduce((a, t) => a + t.latency_ms, 0) / r.turns.length) : null;
  if (ok == null) return `<span class="status na"><span class="dot">?</span>not scored</span>`;
  return `<span class="status ${ok ? "pass" : "fail"}"><span class="dot">${ok ? "✓" : "✕"}</span>${ok ? "pass" : "fail"}`
    + `${r.judge ? ` ${r.judge.correctness}/5` : ""} <span class="ms">${secs(ms)}</span></span>`;
}
function passKey(r) {
  if (!r || r.unsupported || r.blocked) return "na";
  if (r.error) return "fail";
  const v = [r.checks, r.judge?.passed].filter((x) => x != null);
  return v.length ? String(v.every(Boolean)) : "na";
}

let openCase = null;
function renderCases(run) {
  const cats = [...new Set(run.results.map((r) => r.category))].sort();
  const sel = $("catFilter"), prev = sel.value;
  sel.innerHTML = `<option value="">All skills</option>` + cats.map((c) => `<option ${c === prev ? "selected" : ""}>${esc(c)}</option>`).join("");
  const byCase = {};
  for (const r of run.results) (byCase[r.case_id] ??= { category: r.category, rs: {} }).rs[r.bot_id] = r;
  const rows = Object.entries(byCase).filter(([, c]) => !sel.value || c.category === sel.value)
    .filter(([, c]) => !$("diffOnly").checked || new Set(run.bots.map((b) => passKey(c.rs[b.id])).filter((k) => k !== "na")).size > 1);
  let html = `<thead><tr><th>Case</th><th>Skill</th>${run.bots.map((b) => `<th><span class="swatch" style="background:${colorOf(run, b.id)}"></span>${esc(b.label)}</th>`).join("")}</tr></thead><tbody>`;
  for (const [cid, c] of rows) {
    html += `<tr class="case-row" data-case="${esc(cid)}" tabindex="0"><td>${esc(cid)}</td><td class="muted">${esc(c.category)}</td>`
      + run.bots.map((b) => `<td>${caseStatus(c.rs[b.id])}</td>`).join("") + `</tr>`;
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
      h += `<div class="msg user">${esc(t.user)}</div><div class="msg bot">${md(t.bot)}</div><div class="small muted">${secs(t.latency_ms)}</div>`;
    }
    if (r.error) h += `<p class="error">${esc(r.error)}</p>`;
    h += `<div class="verdict">`;
    if (r.checks != null) h += `<div><b>Exact checks:</b> ${r.checks ? "passed" : "failed — " + esc(r.check_failures.join("; "))}</div>`;
    if (r.judge) h += `<div><b>Judge:</b> ${r.judge.passed ? "pass" : "fail"} · correctness ${r.judge.correctness}/5 · helpfulness ${r.judge.helpfulness}/5 · tone ${r.judge.tone}/5${r.judge.hallucinated ? ` · <b class="error">invented facts</b>` : ""}<br>${esc(r.judge.reason)}</div>`;
    if (r.judge_error) h += `<div class="error">Judge error: ${esc(r.judge_error)}</div>`;
    return h + `</div></div>`;
  }).join("") + `</div>`;
}
$("catFilter").onchange = () => currentRun && renderCases(currentRun);
$("diffOnly").onchange = () => currentRun && renderCases(currentRun);

// ---------- Arena ----------
let battleId = null, voted = false;
function bubble(log, cls, text, ms) {
  const d = document.createElement("div");
  d.className = `bubble ${cls}`;
  d.innerHTML = md(text) + (ms != null ? `<span class="ms">${secs(ms)}</span>` : "");
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}
function resetArena() {
  battleId = null; voted = false;
  $("logA").innerHTML = ""; $("logB").innerHTML = "";
  $("nameA").textContent = "Bot A"; $("nameB").textContent = "Bot B";
  $("voteBar").hidden = true;
}
$("arenaForm").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("arenaInput").value.trim();
  if (!text) return;
  if (voted) resetArena();
  const pool = picked("pool");
  if (!battleId && pool.length < 2) { $("arenaMsg").textContent = "Tick at least 2 bots under “Bots in the arena”."; return; }
  $("arenaInput").value = ""; $("arenaSend").disabled = true; $("arenaMsg").textContent = "Both bots are answering…";
  bubble($("logA"), "user", text); bubble($("logB"), "user", text);
  try {
    const r = await api("/api/arena/message", { method: "POST", body: JSON.stringify({ message: text, battle_id: battleId, bots: pool }) });
    battleId = r.battle_id;
    for (const [side, log] of [["a", $("logA")], ["b", $("logB")]]) {
      const x = r[side];
      x.error ? bubble(log, "bot err", "Error: " + x.error) : bubble(log, "bot", x.text || "(empty reply)", x.latency_ms);
    }
    $("voteBar").hidden = false;
    $("arenaMsg").textContent = "Keep chatting, or vote when you've seen enough.";
  } catch (err) { $("arenaMsg").textContent = err.message; }
  finally { $("arenaSend").disabled = false; $("arenaInput").focus(); }
};
document.querySelectorAll("#voteBar button").forEach((b) => (b.onclick = async () => {
  try {
    const r = await api("/api/arena/vote", { method: "POST", body: JSON.stringify({ battle_id: battleId, winner: b.dataset.vote }) });
    voted = true; $("voteBar").hidden = true;
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
  const { rows, votes } = await api("/api/arena/leaderboard");
  $("eloTable").innerHTML = rows.length
    ? `<thead><tr><th>#</th><th>Chatbot</th><th class="num">Elo</th><th class="num">Wins</th><th class="num">Losses</th><th class="num">Ties</th><th class="num">Battles</th></tr></thead><tbody>`
      + rows.map((r, i) => `<tr class="${i === 0 ? "best" : ""}"><td><span class="rank">${i + 1}</span></td><td>${esc(r.label)}</td><td class="num">${fmt(r.elo)}</td><td class="num">${r.wins}</td><td class="num">${r.losses}</td><td class="num">${r.ties}</td><td class="num">${r.battles}</td></tr>`).join("")
      + `</tbody><caption class="muted small" style="caption-side:bottom;text-align:left;padding-top:.5rem">${votes} votes. Ratings settle after roughly 20+ votes per bot.</caption>`
    : `<tbody><tr><td class="muted">No votes yet.</td></tr></tbody>`;
}

// ---------- Start ----------
loadSetup().then(loadRuns).catch((e) => ($("startError").textContent = "Could not load: " + e.message));
