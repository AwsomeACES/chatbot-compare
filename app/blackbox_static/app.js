let importedCases = [];
function qualityScore(value) {
  return typeof value === "number" ? value.toFixed(1) + "%" : "Not scored";
}
const $ = (id) => document.getElementById(id),
  esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
let categories = {},
  categoryDetails = {},
  current = null,
  poll = null,
  archives = {},
  savedJudge = null;
async function api(url, options = {}) {
  const r = await fetch(url, {
    ...options,
    headers: {
      "X-Studio-Request": "1",
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  if (!r.ok) {
    let e = await r.json();
    throw new Error(
      typeof e.detail === "string"
        ? e.detail
        : Array.isArray(e.detail)
          ? e.detail.map((x) => x.msg).join(" ")
          : "Request failed. Please try again.",
    );
  }
  return r.json();
}
function notice(text) {
  $("notice").textContent = text;
  $("notice").hidden = !text;
}
function targetCard(i) {
  return `<div class="bot-column basic-target"><h3>Chatbot ${"ABCD"[i]}</h3><label>Paste your chatbot link<input type="url" id="url-${i}" placeholder="https://your-chatbot.example/chat"></label><div class="upload-choice"><label>Or upload a project ZIP<input type="file" accept=".zip" id="zip-${i}"></label><p id="zip-note-${i}" class="help">ZIP uploads need a separate isolated runner to start testing.</p><button type="button" id="link-${i}" hidden>Use a link instead</button></div></div>`;
}
function advancedTarget(i) {
  return `<div class="bot-column"><h3>Chatbot ${"ABCD"[i]} settings</h3><label>Name<input id="name-${i}" value="Chatbot ${"ABCD"[i]}"></label><label>Connection type<select id="kind-${i}"><option value="auto">Detect automatically</option><option value="rest">REST API</option><option value="openai">OpenAI-compatible endpoint</option><option value="web">Web chat</option><option value="zip">Uploaded ZIP</option></select></label><label>API key or bearer token<input type="password" autocomplete="off" id="token-${i}"></label><label>Target model ID<input id="model-${i}"></label><label>Request message field<input id="message-${i}" value="message"></label><label>Response field<input id="response-${i}" placeholder="Detect common fields automatically"></label><label>Conversation ID field<input id="session-${i}" value="conversation_id"></label><label>History field<input id="history-${i}"></label><label>Extra request values (JSON)<textarea id="defaults-${i}" rows="2" placeholder='{}'></textarea></label><label>Web input selector<input id="input-${i}"></label><label>Web answer selector<input id="answer-${i}"></label><label>Web send button selector<input id="send-${i}"></label></div>`;
}
$("targets").innerHTML = [0, 1, 2, 3].map(targetCard).join("");
$("connection-settings").innerHTML = [0, 1, 2, 3].map(advancedTarget).join("");
for (const i of [2, 3]) {
  $("connection-settings").children[i].insertAdjacentHTML(
    "beforeend",
    `<label>Pricing model alias<input id="cost-model-${i}"></label><label><input type="checkbox" id="cost-local-${i}">Locally hosted model</label>`,
  );
}
const cards = $("targets").children,
  advancedCards = $("connection-settings").children;
function targetCount() {
  return { single: 1, compare: 2, compare3: 3, compare4: 4 }[$("mode").value];
}
function showTargets() {
  for (let i = 0; i < 4; i++) cards[i].hidden = advancedCards[i].hidden = i >= targetCount();
  planned();
}
$("mode").onchange = showTargets;
showTargets();
let uploading = 0,
  starting = false;
for (let i = 0; i < 4; i++) {
  $(`zip-${i}`).onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    uploading++;
    $("start").disabled = true;
    $(`zip-note-${i}`).textContent = "Uploading " + f.name + "...";
    try {
      const data = new FormData();
      data.append("file", f);
      const out = await api("/api/blackbox/upload", { method: "POST", body: data });
      archives[i] = out.id;
      $(`kind-${i}`).value = "zip";
      $(`zip-note-${i}`).textContent = `${out.name}: ${out.reason}`;
      $(`link-${i}`).hidden = false;
    } catch (e) {
      $(`zip-note-${i}`).textContent = e.message;
      notice(e.message);
    } finally {
      uploading--;
      $("start").disabled = !!uploading || starting;
    }
  };
  $(`link-${i}`).onclick = () => {
    delete archives[i];
    $(`kind-${i}`).value = "auto";
    $(`zip-${i}`).value = "";
    $(`zip-note-${i}`).textContent = "Paste the running chatbot link above.";
    $(`link-${i}`).hidden = true;
    $(`url-${i}`).focus();
  };
}
$("performance-consent").onchange = () => {
  const box = document.querySelector('#categories input[value="performance"]');
  if (box) box.checked = $("performance-consent").checked;
  planned();
};
$("references-file").onchange = async (e) => {
  try {
    const text = (await e.target.files[0].text()).replace(/^\uFEFF/, "");
    if (!Array.isArray(JSON.parse(text)))
      throw new Error("Reference JSON must be an array of cases.");
    $("references").value = text;
    notice("Reference cases loaded.");
  } catch (e) {
    notice(e.message);
  }
};
function planned() {
  document
    .querySelectorAll(".case-count")
    .forEach((x) => (x.textContent = "Actual count shown before starting; no padding."));
  $("planned").textContent =
    importedCases.length && $("all-imports")?.checked
      ? importedCases.filter((c) =>
          [...document.querySelectorAll("#categories input:checked")].some(
            (x) => x.value === c.category,
          ),
        ).length + " imported cases selected; built-ins apply only to categories without imports."
      : "Up to " + $("count").value + " cases per selected category. Preview shows actual counts.";
}

function target(i) {
  return {
    name: $(`name-${i}`).value,
    url: $(`url-${i}`).value.trim(),
    kind: $(`kind-${i}`).value,
    archive_id: archives[i] || "",
    request_defaults: JSON.parse($(`defaults-${i}`).value || "{}"),
    token: $(`token-${i}`).value || null,
    model: $(`model-${i}`).value,
    message_field: $(`message-${i}`).value,
    response_field: $(`response-${i}`).value,
    session_field: $(`session-${i}`).value,
    history_field: $(`history-${i}`).value,
    model_alias: $(`cost-model-${i}`).value.trim(),
    local_model: $(`cost-local-${i}`).checked,
    input_selector: $(`input-${i}`).value,
    answer_selector: $(`answer-${i}`).value,
    send_selector: $(`send-${i}`).value,
  };
}
$("start").onclick = async () => {
  starting = true;
  try {
    notice("");
    $("start").disabled = true;
    let refs = JSON.parse($("references").value || "[]");
    const config = {
      targets: [target(0)],
      categories: [...document.querySelectorAll("#categories input:checked")].map((x) => x.value),
      cases_per_category: Number($("count").value),
      custom_cases: importedCases,
      all_imported_cases: $("all-imports")?.checked ?? true,
      include_template_variations: $("template-variations").checked,
      judge_enabled: $("evaluation-method").value === "combined",
      primary_judge_family: $("primary-family").value,
      secondary_judge_enabled: $("second-enabled").checked,
      secondary_judge_model: $("second-model").value,
      secondary_judge_url: $("second-url").value,
      secondary_judge_family: $("second-family").value,
      secondary_judge_token: $("second-token").value || null,
      secondary_sample_rate: Number($("second-sample").value) / 100,
      secondary_judge_consent: $("second-consent").checked,
      secondary_judge_alias: $("second-alias").value,
      secondary_judge_local: $("second-local").checked,
      regression_threshold: Number($("regression-threshold").value),
      references: refs,
      policy: $("policy").value,
      scope: $("scope").value,
      judge_url: $("judge-url").value.trim() || "http://127.0.0.1:1234/v1/chat/completions",
      judge_model: $("judge-model").value,
      judge_token: $("judge-token").value || null,
      consent: $("consent").checked,
      ownership_confirmed: $("ownership").checked,
      judge_consent: $("judge-consent").checked,
      performance_consent: $("performance-consent").checked,
      case_concurrency: Number($("case-concurrency").value),
      target_concurrency: Number($("target-concurrency").value),
      judge_concurrency: Number($("judge-concurrency").value),
      request_pause_seconds: Number($("target-pause").value),
      judge_pause_seconds: Number($("judge-pause").value),
      timeout: Number($("timeout").value),
      max_minutes: Number($("minutes").value),
      max_budget_usd: $("cost-budget").value || null,
      judge_model_alias: $("cost-judge-alias").value.trim(),
      judge_local_model: $("cost-judge-local").checked,
    };
    for (let i = 1; i < targetCount(); i++) config.targets.push(target(i));
    if (!(await confirmReadiness(config))) {
      $("start").disabled = false;
      return;
    }
    if (!(await window.confirmCost(config))) {
      $("start").disabled = false;
      return;
    }
    const run = await api("/api/blackbox/easy-run", {
      method: "POST",
      body: JSON.stringify(config),
    });
    notice((run.setup_notes || []).join(" "));
    await load(run.id);
    history.replaceState(null, "", "?run=" + run.id + "#progress-panel");
    location.hash = "progress-panel";
  } catch (e) {
    notice(e.message);
  } finally {
    starting = false;
    $("start").disabled = !!uploading;
  }
};
let loadSequence = 0;
async function load(id) {
  const seq = ++loadSequence;
  clearTimeout(poll);
  try {
    const next = await api("/api/blackbox/runs/" + id);
    if (seq !== loadSequence) return;
    if (current && current.id !== id) {
      for (const name of ["cases", "summaries"]) {
        $(name).innerHTML = "";
        $(name)._html = null;
      }
    }
    current = next;
    render();
    if (current.judge_changes?.length)
      notice(
        "This run contains multiple judge models. Completed scores were kept; model changes are recorded in the JSON report.",
      );
    if (["queued", "running"].includes(current.status)) poll = setTimeout(() => load(id), 2000);
  } catch (e) {
    if (seq !== loadSequence) return;
    notice("Could not refresh results: " + e.message);
    if (current && ["queued", "running"].includes(current.status)) {
      poll = setTimeout(() => load(id), 5000);
    } else $("start").disabled = !!uploading;
  }
}
function updatePanel(id, html) {
  const root = $(id);
  if (root._html === html) return;
  const opened = [...root.querySelectorAll("details[open][data-disclosure]")].map(
    (x) => x.dataset.disclosure,
  );
  const focus = document.activeElement?.closest("details[data-disclosure]")?.dataset.disclosure;
  const anchor = [...root.querySelectorAll("details[open][data-disclosure]")].find(
    (x) => x.getBoundingClientRect().bottom > 0,
  );
  const anchorKey = anchor?.dataset.disclosure,
    top = anchor?.getBoundingClientRect().top;
  root.innerHTML = html;
  root._html = html;
  for (const item of root.querySelectorAll("details[data-disclosure]")) {
    if (opened.includes(item.dataset.disclosure)) item.open = true;
    if (focus === item.dataset.disclosure)
      item.querySelector("summary").focus({ preventScroll: true });
    if (anchorKey === item.dataset.disclosure)
      window.scrollBy(0, item.getBoundingClientRect().top - top);
  }
}
$("stop").onclick = async () => {
  if (current) await api(`/api/blackbox/runs/${current.id}/stop`, { method: "POST" });
};
function render() {
  const r = current,
    active = ["queued", "running"].includes(r.status);
  $("start").disabled = starting || !!uploading;
  $("progress-panel").hidden = false;
  $("results").hidden = false;
  $("progress").value = r.progress;
  $("result-context").textContent =
    `Saved run: ${new Date(r.started_at).toLocaleString()} | ${r.targets.map((t) => t.name).join(" vs ")} | ${r.status}`;
  $("stage").textContent = `${r.status}: ${r.stage} | ${r.progress}% processed`;
  $("stop").disabled = !active;
  $("formula").textContent = r.score_formula + " " + (r.setup_notes || []).join(" ");
  $("preflight").hidden = !r.preflight;
  if (r.preflight)
    $("preflight").innerHTML =
      "<h2>Connection checks: evaluation could not start</h2><p>" +
      esc(r.preflight.note) +
      "</p><ul>" +
      r.preflight.observations
        .map(
          (o) =>
            "<li><strong>" +
            esc(o.target) +
            ": " +
            esc(o.http_status ? "HTTP " + o.http_status : o.error) +
            "</strong> — " +
            esc(o.meaning) +
            "</li>",
        )
        .join("") +
      "</ul><p><strong>Chat cases executed: " +
      esc(r.preflight.chat_cases_executed) +
      ". No winner can be declared.</strong></p>";
  $("json").href = `/api/blackbox/runs/${r.id}/download?format=json`;
  $("pdf").href = `/api/blackbox/runs/${r.id}/download?format=pdf`;
  updatePanel(
    "summaries",
    r.summary
      .map(
        (s) =>
          `<article class="card"><h2>${esc(s.name)}</h2><div class="score">${qualityScore(s.score)}</div><p>${esc(s.verdict)}</p><h3>Risks in evaluated answers</h3><ul>${s.risks.map((c) => `<li>${esc(categories[c.id] || c.name)}: ${qualityScore(c.score)} (${c.not_tested} not tested)</li>`).join("")}</ul><h3>Missing evidence</h3><p>${(s.missing_evidence || []).map((c) => `${esc(c.name)}: ${c.not_tested} not tested`).join("; ") || "None"}</p><h3>Strengths on tested criteria</h3><p>${s.strengths.map((c) => `${esc(categories[c.id] || c.name)} ${qualityScore(c.score)}`).join(", ") || "No high-scoring tested categories established."}</p><p>All-case request time (may include concurrent load): ${s.mean_seconds === null ? "Not measured" : s.mean_seconds + " seconds"}<br>Request errors: ${s.errors}/${s.requests}<br>${esc(s.request_metrics_basis || "Current recorded attempts")}<br>Sequential speed-test average: ${s.sequential_speed?.mean_seconds == null ? "Not measured" : s.sequential_speed.mean_seconds + " seconds"} (${s.sequential_speed?.requests || 0} requests). Other Studio run traffic paused.<br>Cost details are available in the Cost ($) tab.</p><div class="scroll"><table><thead><tr><th>Category</th><th>Score</th><th>Coverage</th></tr></thead><tbody>${s.categories.map((c) => `<tr><td>${esc(categories[c.id] || c.name)}</td><td>${qualityScore(c.score)}</td><td>${c.tested}/${c.total} (${c.coverage}%)${c.rankable ? "" : " — insufficient coverage"}</td></tr>`).join("")}</tbody></table></div><button type="button" data-baseline="${r.summary.indexOf(s)}" ${r.status !== "completed" || !s.rankable ? "disabled" : ""}>Save this bot as regression baseline</button><h3>Failing conversation examples</h3>${
            s.examples
              .map((id) => {
                const c = r.cases.find((c) => c.id === id),
                  i = r.summary.indexOf(s),
                  x = c.results[i];
                return `<details data-disclosure="example-${i}-${esc(c.id)}"><summary>${esc(c.name)}</summary><p>${esc(x.reason)}</p>${x.transcript.map((t) => `<div class="transcript">Customer: ${esc(t.input)}<br>Bot: ${esc(t.output || t.error)}</div>`).join("")}</details>`;
              })
              .join("") || "<p>No scored failing examples recorded.</p>"
          }<p><strong>Next step:</strong> Open low-scoring cases below. Correct the behavior described in the judge's explanation; for Not tested, resolve its configuration or connection reason and rerun.</p></article>`,
      )
      .join(""),
  );
  window.renderAdvancedResults(r, categories);
  drawDashboard(r, categories);
  window.renderCost(r);
  renderCases();
}
function renderCases() {
  if (!current) return;
  const query = $("search").value.toLowerCase(),
    cat = $("filter").value;
  const rows = current.cases.filter(
    (c) =>
      (!cat || c.category === cat) && (!query || JSON.stringify(c).toLowerCase().includes(query)),
  );
  updatePanel(
    "cases",
    `<p>${rows.length} cases. Expand any row to see exact conversations and judging evidence.</p>` +
      rows
        .map(
          (c) =>
            `<details class="case-row" data-disclosure="case-${esc(c.id)}"><summary>${esc(c.name)} — case ${esc(c.id.split("-").pop().replace(/^0+/, ""))} ${c.results.map((r, i) => `<span class="badge ${r.status}">${current.targets.length > 1 ? "ABCD"[i] + ": " : ""}${r.status === "not_tested" ? "Not tested" : r.status} | ${qualityScore(r.score)}${r.needs_review ? " / Evidence needs review" : ""}</span>`).join(" ")}</summary><p><strong>Expected:</strong> ${esc(c.expected)}</p><div class="columns">${c.results.map((r, i) => `<div><h3>${esc(current.targets[i].name)}</h3><p><strong>Judge:</strong> ${esc(r.reason)} ${r.estimated ? "(AI estimate)" : ""} ${r.needs_review ? "<strong>Evidence needs review: " + esc(r.review_reason) + "</strong>" : ""}</p><p>Time: ${r.seconds === null ? "Not measured" : r.seconds.toFixed(2) + " seconds"}</p>${r.deterministic_checks?.length ? `<h4>Exact checks</h4><ul>${r.deterministic_checks.map((x) => `<li>${esc(x.kind)}: ${esc(x.term)} — ${x.met ? "Satisfied" : "Failed"}</li>`).join("")}</ul>` : ""}${r.secondary_judge ? `<h4>Second judge</h4><p>${qualityScore(r.secondary_judge.score)} — ${esc(r.secondary_judge.reason)} ${r.secondary_judge.status === "judged" ? (r.secondary_judge.agrees ? "Agrees with primary pass/fail" : "Disagrees with primary pass/fail") : "Not tested"}</p><p>${esc((r.secondary_judge.evidence || []).join(" | "))}</p>` : ""}${r.transcript.map((t) => `<div class="transcript"><strong>Customer:</strong> ${esc(t.input)}<br><br><strong>Bot:</strong> ${esc(t.output || t.error || "No response")}</div>`).join("") || "<p>No conversation was recorded.</p>"}${r.unmatched_evidence?.length ? `<p><strong>Unverified quotes:</strong> ${esc(r.unmatched_evidence.join(" | "))}</p>` : ""}${r.evidence ? `<p><strong>Evidence:</strong> ${esc(r.evidence.join(" | "))}</p>` : ""}</div>`).join("")}</div>${
              current.targets.length > 1
                ? `<p><strong>Pairwise:</strong> ${Object.entries(c.pairs || { "0:1": c.pair })
                    .map(([key, p]) =>
                      esc(
                        key
                          .split(":")
                          .map((i) => "ABCD"[Number(i)])
                          .join(" vs ") +
                          ": " +
                          p.reason +
                          (p.needs_review ? " Evidence needs review" : ""),
                      ),
                    )
                    .join("<br>")}</p>`
                : ""
            }<small>Case ${esc(c.id)} | ${esc(c.variant_note)}<br>Evidence digest: ${esc(c.evidence_sha256 || "Not available")}</small></details>`,
        )
        .join(""),
  );
}
$("search").oninput = renderCases;
$("filter").onchange = renderCases;
$("count").onchange = planned;
$("history").onclick = async () => {
  try {
    const runs = await api("/api/blackbox/runs");
    $("history-panel").hidden = false;
    $("history-panel").innerHTML =
      "<h2>Previous black-box runs</h2>" +
      runs
        .map(
          (r) =>
            `<p><button data-run="${esc(r.id)}">${esc(new Date(r.started_at).toLocaleString())} — ${esc(r.targets.map((t) => t.name).join(" vs "))} — ${esc(r.status)}</button> <button data-delete-run="${esc(r.id)}" ${["running", "queued"].includes(r.status) ? "disabled" : ""}>Delete this run</button></p>`,
        )
        .join("") +
      '<p><a href="/api/blackbox/history" target="_blank" rel="noopener">View historical data from the previous Studio version (different scoring)</a></p>';
    document.querySelectorAll("[data-run]").forEach((b) => (b.onclick = () => load(b.dataset.run)));
    location.hash = "history-panel";
  } catch (e) {
    notice(e.message);
  }
};
(async () => {
  try {
    const data = await api("/api/blackbox/capabilities");
    categories = data.categories;
    categoryDetails = data.category_details || {};
    $("categories").innerHTML = Object.entries(categories)
      .map(
        ([k, v]) =>
          `<label class="suite-card"><span class="suite-title"><input type="checkbox" value="${k}" ${["hallucination", "bias", "guardrails", "injection"].includes(k) ? "checked" : ""}>${esc(v)}</span>${categoryDetails[k] ? `<small>${esc(categoryDetails[k].description)}</small><small class="suite-requires"><strong>To run:</strong> ${esc(categoryDetails[k].requires)}</small>` : ""}<small class="case-count"></small></label>`,
      )
      .join("");
    $("filter").innerHTML =
      '<option value="">All categories</option>' +
      Object.entries(categories)
        .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`)
        .join("");
    document.querySelectorAll("#categories input").forEach(
      (x) =>
        (x.onchange = () => {
          if (x.value === "performance") $("performance-consent").checked = false;
          planned();
        }),
    );
    $("capabilities").textContent =
      "Package availability: " +
      Object.entries(data.packages)
        .map(([k, v]) => `${k}: ${v ? "installed" : "not installed"}`)
        .join("; ") +
      ". Models and adapters must also be configured; this is not proof they have run.";
    const defaults = await api("/api/blackbox/defaults");
    savedJudge = defaults;
    $("judge-status").textContent = defaults.configured
      ? `${defaults.model} via ${defaults.provider}${defaults.external ? " (external provider)" : ""}. Prompts, facts and replies are shared only with your consent.`
      : "No saved judge. Add a model and connection in Advanced once, or use Exact checks only with an imported exact-check case set.";
    $("online").textContent = "System online";
    planned();
    const requestedRun = new URLSearchParams(location.search).get("run");
    if (requestedRun) await load(requestedRun);
    else {
      const runs = await api("/api/blackbox/runs");
      if (runs.length) await load(runs[0].id);
    }
  } catch (e) {
    $("online").textContent = "Connection failed";
    notice(e.message);
  }
})();

for (const id of ["judge-url", "judge-model"])
  $(id).addEventListener("input", () => {
    $("judge-consent").checked = false;
    try {
      const model = $("judge-model").value.trim();
      const host = new URL(
        $("judge-url").value.trim() || "http://127.0.0.1:1234/v1/chat/completions",
      ).hostname;
      $("judge-status").textContent = model
        ? `Override: ${model} via ${host}. Enabling sends prompts, facts and replies here.`
        : savedJudge?.configured
          ? `${savedJudge.model} via ${savedJudge.provider}. Saved backend judge; enabling shares prompts, facts and replies.`
          : "No saved judge. Configure one in Advanced.";
    } catch {
      $("judge-status").textContent = "Enter a complete judge endpoint URL in Advanced.";
    }
  });

async function confirmReadiness(config) {
  const preview = await api("/api/blackbox/preview", {
    method: "POST",
    body: JSON.stringify(config),
  });
  const dialog = $("readiness-preview");
  $("readiness-body").innerHTML =
    "<p>" +
    esc(preview.note) +
    "</p>" +
    preview.categories
      .map(
        (r) =>
          `<article><strong>${esc(r.name)}: ${r.ready ? "Ready" : "Will not run"} — ${r.planned_cases} cases (${esc((r.sources || []).join(", "))})</strong><p>${esc(r.note)} ${r.reasons.map(esc).join(" ")}</p></article>`,
      )
      .join("");
  const go = $("readiness-go");
  go.disabled = !preview.runnable_categories.length;
  go.textContent = preview.excluded_categories.length
    ? "Exclude unavailable checks and continue"
    : "Continue to cost estimate";
  dialog.showModal();
  return new Promise((resolve) => {
    const finish = (ok) => {
      dialog.close();
      resolve(ok);
    };
    go.onclick = () => {
      config.categories = preview.runnable_categories;
      finish(true);
    };
    $("readiness-cancel").onclick = () => finish(false);
    dialog.oncancel = (e) => {
      e.preventDefault();
      finish(false);
    };
  });
}

$("case-set-file").onchange = async (e) => {
  try {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 500000) throw new Error("Case set must be under 500 KB.");
    const rows = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
    const data = await api("/api/blackbox/case-set/validate", {
      method: "POST",
      body: JSON.stringify(rows),
    });
    importedCases = data.cases;
    $("case-set-status").textContent =
      "Loaded " +
      importedCases.length +
      " cases. Replaces built-in cases in these categories: " +
      Object.entries(data.counts)
        .map(([k, n]) => k + " (" + n + ")")
        .join(", ");
    planned();
  } catch (e) {
    notice(e.message);
  }
};
$("case-set-clear").onclick = () => {
  importedCases = [];
  $("case-set-file").value = "";
  $("case-set-status").textContent = "Using built-in cases.";
  planned();
};

$("summaries").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-baseline]");
  if (!button || !current) return;
  try {
    button.disabled = true;
    const result = await api(
      `/api/blackbox/runs/${current.id}/baseline?bot=${button.dataset.baseline}`,
      { method: "POST" },
    );
    notice(result.target + ": " + result.note);
  } catch (err) {
    notice(err.message);
  } finally {
    button.disabled = false;
  }
});
$("evaluation-method").onchange = () => {
  if ($("evaluation-method").value === "exact") {
    $("second-enabled").checked = false;
    $("judge-consent").checked = false;
    $("second-consent").checked = false;
  }
};
for (const id of ["second-model", "second-url", "second-token", "second-family"])
  $(id).addEventListener("input", () => {
    $("second-consent").checked = false;
  });
