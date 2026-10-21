/* Ten-case screen. Credentials remain in password fields and request bodies only. */
const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
let pollBusy = false;
let pollController,
  pollRequestId,
  pollGeneration = 0;
const resultCache = new Map();
let hydrateRequested = !!new URLSearchParams(location.search).get("run");
let settings,
  runId = new URLSearchParams(location.search).get("run"),
  botCount = 0,
  nextBot = 0,
  current;
const tell = (message) => {
  $("notice").className = "notice";
  $("notice").textContent = message;
};
async function api(url, body, method = "POST", options = {}) {
  const response = await fetch(
    url,
    body === undefined
      ? options
      : {
          method,
          headers: {
            "Content-Type": "application/json",
            "X-Studio-Request": "1",
          },
          body: JSON.stringify(body),
          ...options,
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || response.status),
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function addBot() {
  if (botCount >= 4) return;
  const i = nextBot++;
  botCount++;
  $("bots").insertAdjacentHTML(
    "beforeend",
    `<article class="bot" data-bot="${i}"><h3>Chatbot ${i + 1}</h3><div class="grid"><label>Name<input data-field="name" value="Chatbot ${i + 1}"></label><label data-chat-only>Chat link or API endpoint<input data-field="url" placeholder="https://your-bot.example/chat"></label></div><details data-chat-only><summary>Connection settings (optional)</summary><div class="grid"><label>Type<select data-field="kind"><option value="auto">Detect automatically</option><option value="rest">REST API</option><option value="openai">OpenAI compatible</option><option value="web">Web chat widget</option></select></label><label>API key<input data-field="token" type="password" autocomplete="off"></label><label>Bot model / cost alias<input data-field="model"></label><label>Request message field<input data-field="message_field" value="message"></label><label>Response field<input data-field="response_field" placeholder="Detect common fields"></label><label>History field<input data-field="history_field"></label><label>Conversation ID field<input data-field="session_field" value="conversation_id"></label><label>Extra request JSON<textarea data-field="defaults">{}</textarea></label><label>Chat input selector<input data-field="input_selector"></label><label>Bot reply selector<input data-field="answer_selector"></label><label>Send button selector<input data-field="send_selector"></label></div></details><button type="button" class="remove-bot">Remove bot</button></article>`,
  );
  const card = $("bots").lastElementChild;
  card.querySelector(".remove-bot").onclick = () => {
    card.remove();
    botCount--;
    planned();
  };
  planned();
}
function planned() {
  $("add-bot").disabled = botCount >= 4;
  document.querySelectorAll(".remove-bot").forEach((button) => (button.hidden = botCount <= 1));
  if (!settings) return;
  const repeats = [...document.querySelectorAll("[data-repeat]")].reduce(
    (n, e) => n + Number(e.value) * (settings.scenario_sets?.[e.dataset.repeat]?.length || 1),
    0,
  );
  $("planned").textContent =
    `${settings.cases.length} categories · ${repeats} results per bot · ${botCount} ${botCount === 1 ? "bot" : "bots"}`;
  const counts = [...document.querySelectorAll("[data-repeat]")].map((e) => e.value);
  $("repeat-all").value = counts.every((n) => n === counts[0]) ? counts[0] || "" : "";
  $("repeat-all").placeholder = "Custom";
  syncSetup();
}
function syncSetup() {
  const hasMode = (mode) => document.querySelector(`[data-mode="${mode}"]`).checked;
  const chat = hasMode("black"),
    source = hasMode("white"),
    knowledge = hasMode("gray");
  $("judge-section").hidden = !chat && !knowledge;
  $("chat-test-options").hidden = !chat;
  $("source-plan").hidden = chat;
  $("source-plan").textContent = source
    ? "Check uploaded files for security issues. Source scans do not test live chatbot answers."
    : "Review your uploaded prompts, knowledge and logs. Missing evidence is clearly marked in the report.";
  $("judge-consent-row").hidden = !chat && !knowledge;
  $("private-settings").hidden = !source && !knowledge;
  $("run-step").textContent = chat || knowledge ? "3" : "2";
  $("mode-help").textContent =
    [
      chat ? "Black-box testing: use a working chat link or API endpoint." : "",
      source ? "Source code: upload a ZIP below. Its code will not be executed." : "",
      knowledge ? "Gray-box testing: add the files you want reviewed." : "",
    ]
      .filter(Boolean)
      .join(" ") || "Select at least one test type.";
  document.querySelectorAll("[data-chat-only]").forEach((e) => (e.hidden = !chat));
  const selected = [...document.querySelectorAll(".judge")].filter(
    (e) => e.querySelector("[data-enabled]").checked && !e.querySelector("[data-fallback]").checked,
  );
  $("judge-summary").textContent = selected.length
    ? "Judge: " +
      selected.map((e) => e.querySelector("[data-model]").value || e.dataset.label).join(", ")
    : "Choose a judge below to score the answers.";
}

function judges() {
  return [...document.querySelectorAll(".judge")]
    .filter((e) => e.querySelector("[data-enabled]").checked)
    .map((e) => ({
      model: e.querySelector("[data-model]").value.trim(),
      url: e.dataset.url,
      token: e.querySelector("[data-key]").value || null,
      local: e.dataset.local === "true",
      fallback: e.querySelector("[data-fallback]").checked,
    }));
}
function configuration() {
  const targets = [...document.querySelectorAll(".bot")].map((e) => {
    const val = (k) => e.querySelector(`[data-field=${k}]`).value.trim();
    return {
      name: val("name"),
      url: val("url"),
      kind: e.dataset.archive && !val("url") ? "zip" : val("kind"),
      archive_id: e.dataset.archive || "",
      token: val("token") || null,
      model: val("model"),
      model_alias: val("model"),
      message_field: val("message_field"),
      response_field: val("response_field"),
      history_field: val("history_field"),
      session_field: val("session_field"),
      request_defaults: JSON.parse(val("defaults") || "{}"),
      input_selector: val("input_selector"),
      answer_selector: val("answer_selector"),
      send_selector: val("send_selector"),
    };
  });
  return {
    targets,
    judges: judges(),
    consent: $("consent").checked,
    ownership_confirmed: $("ownership").checked,
    judge_consent: $("consent").checked,
    simple_mode: true,
    repeat_counts: Object.fromEntries(
      [...document.querySelectorAll("[data-repeat]")].map((e) => [
        e.dataset.repeat,
        Number(e.value),
      ]),
    ),
    references: JSON.parse($("references").value || "[]"),
    policy: $("policy").value,
    scope: $("scope").value,
    ...settings.execution,
    retention_days: Number($("retention").value),
  };
}
const money = (n, local = false) => {
  if (n == null) return "Unknown";
  if (n === 0 && local) return "$0 (local)";
  return n > 0 && n < 100 ? "<$0.0001" : "$" + (n / 1000000).toFixed(6);
};
const costMoney = (row) =>
  row?.cost_micro_usd != null &&
  Number(row.exact_micro_usd) > 0 &&
  Number(row.exact_micro_usd) < 100
    ? "<$0.0001"
    : money(row?.cost_micro_usd, row?.calls > 0 && row.local_calls === row.calls);
function table(head, rows) {
  return `<div class="scroll"><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function bar(value, max) {
  return `<div class="bar-track"><div class="bar" style="width:${Math.min(100, Math.max(0, (Number(value) / Math.max(1, max)) * 100))}%"></div></div>`;
}
function render(run) {
  current = run;
  window.StudioUI.updateRun(run);
  $("use-run-settings").disabled = !run.config.simple_mode;
  window.dispatchEvent(
    new CustomEvent("studio:run-rendered", {
      detail: {
        id: run.id,
        status: run.status,
        overrides: run.cases.flatMap((c) => c.results).filter((r) => r.human_review_note).length,
      },
    }),
  );
  if (hydrateRequested && run.config.simple_mode) {
    $("bots").innerHTML = "";
    botCount = 0;
    nextBot = 0;
    run.targets.forEach((target) => {
      addBot();
      const card = $("bots").lastElementChild;
      card.dataset.archive = target.archive_id || "";
      for (const [key, value] of Object.entries(target)) {
        const field = card.querySelector(`[data-field="${key}"]`);
        if (field && key !== "token") field.value = typeof value === "string" ? value : "";
      }
      if (target.kind === "zip") card.querySelector("[data-field=kind]").value = "auto";
      card.querySelector("[data-field=defaults]").value = JSON.stringify(
        target.request_defaults || {},
      );
    });
    document
      .querySelectorAll("[data-repeat]")
      .forEach(
        (e) => (e.value = run.config.repeat_counts[e.dataset.repeat] || settings.default_repeats),
      );
    $("policy").value = run.config.policy;
    $("scope").value = run.config.scope;
    $("references").value = JSON.stringify(run.config.references || []);
    hydrateRequested = false;
    planned();
  }
  document.querySelectorAll(".judge").forEach((e) => {
    const model = e.querySelector("[data-model]").value;
    const event = [...(run.audit || [])]
      .reverse()
      .find(
        (a) =>
          a.model === model && ["judge_verdict", "judge_unavailable", "fallback"].includes(a.event),
      );
    const badge = e.querySelector("[data-status]");
    if (badge)
      badge.textContent = event
        ? event.event === "judge_unavailable"
          ? "Unavailable: " + event.reason
          : "Working: " + model
        : "Not checked yet";
  });
  const active = ["running", "queued"].includes(run.status);
  $("stop").disabled = !active;
  $("apply-judges").disabled = !active;
  $("apply-judges").hidden = !active;
  $("resume").disabled =
    active || !run.cases.some((c) => c.results.some((r) => r.status === "not_tested"));
  const done = run.cases.filter((c) => c.completed).length;
  $("stage").textContent =
    `${run.status}: ${run.stage} • ${done}/${run.cases.length} cases processed. Scored coverage is shown below.`;
  $("progress").value = run.progress;
  const studio = run.studio;
  const resultCases =
    run.protocol_snapshot?.cases ||
    settings.cases.filter((c) => run.categories.includes(c.category));
  const caseName = (item) =>
    settings.cases.find((c) => c.category === item.category)?.name || item.name;
  if (!studio) {
    [
      "scores",
      "relevance-charts",
      "costs",
      "case-results",
      "audit",
      "downloads",
      "bias-details",
      "integrity",
      "live-progress",
    ].forEach((id) => ($(id).innerHTML = ""));
    $("resume").disabled = true;
    $("verdict").innerHTML =
      `<p>This is an older protocol. <a href="/index.html?run=${esc(run.id)}#results">Open its complete historical results</a>.</p>`;
    return;
  }
  $("verdict").innerHTML =
    `<div class="verdict-card"><h3>${studio.winner == null ? (studio.bots.length === 1 ? "Evaluation summary" : "Comparison summary") : "Winner: " + esc(run.targets[studio.winner].name)}</h3><p>${esc(studio.confidence_note)}</p>${studio.warnings.length ? `<p class="unknown">${studio.warnings.map(esc).join(" ")}</p>` : ""}</div><details class="subtle-details"><summary>How to read these scores</summary><p>${esc(studio.formula)}</p><p>Not tested is missing evidence, not a failed answer. It contributes zero to this evaluation index. Measured quality and coverage are shown separately.</p></details>`;
  if (studio.comparison) {
    const comparison = studio.comparison;
    $("verdict").innerHTML +=
      `<details class="subtle-details"><summary>Comparison evidence and review checks</summary><p>${esc(comparison.method_note)}</p><p>Confidence target across all bot pairs: ${esc(Math.round(100 * comparison.policy.confidence))}%. Saved tie margin: ${esc(comparison.tie_margin)} points. Minimum distinct scenarios: ${esc(comparison.policy.min_scenarios)}, including ${esc(comparison.policy.min_scenarios_per_category)} per category. More repeats cannot replace additional scenarios.</p>` +
      (comparison.pairs.length
        ? table(
            ["Bots", "Paired scenarios", "Score difference", "Adjusted interval", "Decision"],
            comparison.pairs.map((p) => [
              `${esc(studio.bots[p.a].name)} vs ${esc(studio.bots[p.b].name)}`,
              esc(p.scenarios),
              p.difference == null ? "Not measured" : esc(p.difference),
              p.low == null ? "Insufficient evidence" : `${esc(p.low)} to ${esc(p.high)}`,
              esc(p.reason),
            ]),
          )
        : "") +
      table(
        ["Bot", "Review checks", "Reason"],
        comparison.readiness.map((r) => [
          esc(studio.bots[r.bot].name),
          r.meets_checks ? "Meets configured checks" : "Review required",
          esc(r.reasons.join(" ") || "No open review items; all category thresholds met."),
        ]),
      ) +
      "<p>These checks support a human release decision. They do not certify production readiness.</p></details>";
  }
  if (resultCases.length < settings.cases.length) {
    $("verdict").innerHTML +=
      `<p>This saved run contains ${resultCases.length} checks. New checks are available in <a href="#evaluate" data-view="evaluate">Evaluate</a>. Historical scores are unchanged.</p>`;
  }
  $("scores").innerHTML =
    `<div class="grid">${studio.bots
      .map(
        (b) =>
          `<article class="metric"><h3>${esc(b.name)}</h3><span class="pill">${b.tested === b.planned ? "Fully scored" : "Partial coverage"}</span><p class="muted">Overall score</p><div class="score">${b.score}<small>/100</small></div><p><strong>${b.tested}/${b.planned}</strong> outcomes scored · ${b.planned ? Math.round((100 * b.tested) / b.planned) : 0}% coverage</p><p>Strongest measured check: ${esc([...b.categories].filter((c) => c.tested).sort((a, z) => z.quality - a.quality)[0]?.name || "Not established")}<br>Lowest category scores: ${esc(
            [...b.categories]
              .sort((a, z) => a.score - z.score)
              .slice(0, 3)
              .map((c) => c.name)
              .join(", "),
          )}</p>${bar(b.score, 100)}</article>`,
      )
      .join("")}</div>` +
    '<h3 class="chart-heading">Scores by category</h3>' +
    table(
      ["Category", ...studio.bots.map((b) => b.name), "Result"],
      resultCases.map((item) => {
        const groups = studio.bots.map((b) => b.categories.find((c) => c.id === item.category));
        const categoryResult = studio.comparison?.category_results?.[item.category];
        const complete = groups.every((g) => g.planned > 0 && g.tested === g.planned);
        const savedMargin = run.protocol_snapshot?.tie_margin;
        const high = Math.max(...groups.map((g) => g.score));
        const win = categoryResult
          ? categoryResult.leaders.map((i) => studio.bots[i].name)
          : groups
              .map((g, i) =>
                savedMargin != null && high - g.score <= savedMargin ? studio.bots[i].name : null,
              )
              .filter(Boolean);
        return [
          esc(caseName(item)),
          ...groups.map(
            (g) =>
              `${g.low_confidence ? '<span class="pill">Low confidence</span> ' : ""}${g.score}% ${bar(g.score, 100)}<small>${g.tested}/${g.planned} scored; measured quality: ${g.quality == null ? "Not measured" : g.quality + "%"}; largest within-case repeat spread: ${g.repeat_spread ?? g.spread ?? "Unknown"} points</small>`,
          ),
          esc(
            categoryResult && !categoryResult.leaders.length
              ? categoryResult.reason
              : !complete
                ? "Incomplete evidence"
                : studio.bots.length === 1
                  ? "Scored"
                  : win.length > 1
                    ? "Tie"
                    : win[0] || "Saved comparison policy unavailable",
          ),
        ];
      }),
    );
  const relevanceKeys = ["hallucination_relevant", "hallucination_irrelevant"].filter((key) =>
    studio.bots.some((b) => b.categories.some((c) => c.id === key)),
  );
  $("relevance-charts").hidden = !relevanceKeys.length;
  $("relevance-charts").innerHTML =
    '<h3>Relevance and irrelevance — separate scores</h3><div class="grid">' +
    relevanceKeys
      .map((key) => {
        const label = settings.cases.find((c) => c.category === key)?.name || key;
        return `<article class="metric"><h4>${esc(label)}</h4>${studio.bots
          .map((bot) => {
            const group = bot.categories.find((c) => c.id === key);
            return group
              ? `<p><strong>${esc(bot.name)}: ${group.tested ? group.quality + "% measured quality" : "Not tested yet"}</strong></p>${bar(group.quality ?? 0, 100)}<small>${group.tested}/${group.planned} scored; configured index: ${group.score}%. Missing evidence contributes zero to the index.</small>`
              : `<p>${esc(bot.name)}: Not tested in this saved run</p>`;
          })
          .join("")}</article>`;
      })
      .join("") +
    "</div>";
  const costs = run.costs;
  if (costs?.available) {
    const rows = [
      ...(costs.bots || []).map((b) => ({ ...b, label: "Bot: " + b.name })),
      ...(costs.breakdowns?.model_alias || [])
        .filter((b) => b.evaluation?.calls)
        .map((b) => ({ ...b.evaluation, label: "Judge: " + b.name })),
    ];
    const max = Math.max(1, ...rows.map((r) => r.input_tokens + r.output_tokens));
    const maxCost = Math.max(1, ...rows.map((r) => r.cost_micro_usd || 0));
    $("costs").innerHTML =
      '<div class="cost-summary"><span>Bot cost <strong>' +
      costMoney(costs.bot) +
      "</strong></span><span>Judge cost <strong>" +
      costMoney(costs.evaluation) +
      "</strong></span></div>" +
      table(
        [
          "Bot / judge",
          "Input",
          "Output",
          "Reasoning (included in output)",
          "Tokens chart",
          "USD cost",
          "Cost chart",
        ],
        rows.map((r) => [
          esc(r.label),
          r.input_tokens,
          r.output_tokens,
          r.reasoning_tokens || 0,
          bar(r.input_tokens + r.output_tokens, max),
          costMoney(r),
          r.cost_micro_usd == null ? "Unknown" : bar(r.cost_micro_usd, maxCost),
        ]),
      ) +
      `<p>Bot total: ${costMoney(costs.bot)}. Evaluation total: ${costMoney(costs.evaluation)}. Hidden bot calls require its own telemetry. Token totals can include estimates for failed or opaque calls; JSON records each source.</p>`;
  } else
    $("costs").innerHTML =
      '<p class="empty-state">Cost is unavailable for this run. Missing usage is never treated as free.</p>';
  const openIds = new Set(
    [...document.querySelectorAll("#case-results details[open]")].map((e) => e.dataset.case),
  );

  function caseEvidence(category) {
    return run.cases
      .filter((c) => c.category === category)
      .map(
        (c) =>
          `<div class="case-evidence"><h4>${esc(c.name)} · case ${c.scenario_index || 1}, repeat ${c.repeat}</h4><div class="grid">${c.results
            .map(
              (r, i) =>
                `<article><strong>${esc(run.targets[i].name)} <span class="pill">${esc(r.status.replaceAll("_", " "))}</span></strong><p>Score: ${r.score == null ? "Not tested (index contribution 0)" : r.score + "/100"}</p><p>${r.human_review_note ? "<strong class=badge>Overridden — reason logged</strong> " : ""}${r.needs_review ? "<strong>Needs human review</strong> " : ""}${esc(r.reason)}</p>${(r.judges || []).map((j) => `<p class="judge-reason">Judge: ${esc(j.model)} — ${j.score}%<br>Evidence: ${j.evidence.map(esc).join(" | ")}</p>`).join("")}${r.transcript
                  .map(
                    (t) => `<div class="transcript"><strong>User:</strong> ${esc(t.input)}
<strong>Bot:</strong> ${esc(t.output || t.error || "No response")}
Time: ${t.seconds ?? "Unknown"} seconds</div>`,
                  )
                  .join(
                    "",
                  )}${!active && r.transcript.some((t) => t.output) ? `<button data-review="${esc(c.id)}" data-slot="${i}">Add human review</button>` : ""}</article>`,
            )
            .join("")}</div></div>`,
      )
      .join("");
  }
  $("case-results").innerHTML = resultCases
    .map((item) => {
      const records = run.cases.filter((c) => c.category === item.category);
      const rows = records.flatMap((c) => c.results);
      const scored = rows.filter(
        (r) => r.score != null && ["passed", "failed"].includes(r.status),
      ).length;
      return `<details data-case="${esc(item.category)}" ${openIds.has(item.category) ? "open" : ""}><summary>${esc(caseName(item))}<span class="summary-meta">${scored}/${rows.length} outcomes scored</span></summary><div data-case-body>${openIds.has(item.category) ? caseEvidence(item.category) : ""}</div></details>`;
    })
    .join("");
  // Load evidence only when requested, rather than inserting hundreds of hidden transcripts.
  $("case-results")
    .querySelectorAll("details[data-case]")
    .forEach((details) => {
      details.ontoggle = () => {
        const body = details.querySelector("[data-case-body]");
        if (details.open && !body.hasChildNodes())
          body.innerHTML = caseEvidence(details.dataset.case);
      };
    });
  $("case-results").onclick = async (event) => {
    const button = event.target.closest("[data-review]");
    if (!button) return;
    const score = prompt("Human-reviewed score (0–100)");
    if (score === null) return;
    const note = prompt("Explain your review (at least 10 characters)");
    if (!note) return;
    try {
      await api(`/api/studio/runs/${runId}/override`, {
        case_id: button.dataset.review,
        bot: Number(button.dataset.slot),
        score: Number(score),
        note,
      });
      await poll();
    } catch (error) {
      tell(error.message);
    }
  };
  $("audit").innerHTML =
    `<p>Run ID: ${esc(run.id)}. Agreement measured on ${studio.agreement_cases || 0} conversations with distinct valid judge models. Agreement: ${studio.agreement_percent == null ? "Not measured" : studio.agreement_percent + "%"}. ${esc(studio.agreement_definition || "")}</p><pre>${esc(JSON.stringify(run.audit || [], null, 2))}</pre>`;
  $("bias-panel").hidden = !studio.bots.some((b) => b.bias_subtests?.length);
  renderGovernanceExtras(run);
  $("downloads").innerHTML =
    `<a class="button" href="/api/blackbox/runs/${run.id}/download?format=pdf">Download PDF</a><a class="button" href="/api/blackbox/runs/${run.id}/download?format=json">Export JSON</a><a class="button" href="#governance" data-view="governance">Governance →</a>`;
}
async function poll() {
  if (!runId || (pollBusy && pollRequestId === runId)) return;
  pollController?.abort();
  pollController = new AbortController();
  const generation = ++pollGeneration;
  pollBusy = true;
  const requestedId = runId;
  pollRequestId = requestedId;
  try {
    const run = await api(`/api/blackbox/runs/${requestedId}`, undefined, "GET", {
      signal: pollController.signal,
    });
    if (generation !== pollGeneration || requestedId !== runId) return;
    resultCache.set(run.id, run);
    if (resultCache.size > 10) resultCache.delete(resultCache.keys().next().value);
    render(run);
  } catch (error) {
    if (generation === pollGeneration && requestedId === runId && error.status === 404) {
      resultCache.delete(requestedId);
      window.StudioUI.selectRun(null, { replace: true });
      tell("This test is no longer available. Choose another test or start a new one.");
      return;
    }
    if (generation === pollGeneration && requestedId === runId && error.name !== "AbortError")
      tell(error.message);
  } finally {
    if (generation === pollGeneration) pollBusy = false;
  }
}
async function loadHistory() {
  const runs = await api("/api/blackbox/runs");
  window.StudioUI.setRuns(runs);
  $("history").innerHTML = runs
    .map(
      (r) =>
        `<button data-run="${esc(r.id)}">${esc(r.targets?.map((b) => b.name).join(" vs ") || r.id)} — ${esc(r.status)}</button>`,
    )
    .join(" ");
  document.querySelectorAll("[data-run]").forEach(
    (e) =>
      (e.onclick = () => {
        window.StudioUI.selectRun(e.dataset.run);
        window.StudioUI.navigate("results");
      }),
  );
}
async function boot() {
  settings = await api("/api/studio/settings");
  $("suite-intro").textContent =
    `${settings.cases.length} categories cover accuracy, safety, fairness and helpfulness.`;
  addBot();
  $("test-preview").innerHTML = settings.cases.map((c) => `<span>${esc(c.name)}</span>`).join("");
  $("checks").innerHTML = settings.cases
    .map(
      (c) =>
        `<label class="check">${esc(c.name)}<br><small>${esc(settings.descriptions?.[c.category] || "")}</small><br><small>${settings.scenario_sets?.[c.category]?.length || 1} distinct cases × repeats per case</small><br>Repeats <input type="number" min="1" max="20" value="${settings.default_repeats}" data-repeat="${c.category}"></label>`,
    )
    .join("");
  document.querySelectorAll("[data-repeat]").forEach((e) => (e.oninput = planned));
  $("repeat-all").onchange = () => {
    if (!$("repeat-all").checkValidity() || !$("repeat-all").value) {
      tell("Enter a whole number from 1 to 20 for repeats.");
      planned();
      return;
    }
    document.querySelectorAll("[data-repeat]").forEach((e) => (e.value = $("repeat-all").value));
    planned();
  };
  if (!runId) {
    ["stop", "apply-judges", "resume"].forEach((id) => ($(id).disabled = true));
    $("apply-judges").hidden = true;
  }
  const saved = settings.saved_judge;
  let list = settings.judges;
  if (saved.configured)
    list = [
      {
        label:
          list.find((j) => j.url === saved.endpoint && j.model === saved.model)?.label ||
          "Saved judge",
        credential_configured: true,
        model: saved.model,
        url: saved.endpoint,
        local: !saved.external,
      },
      ...list.filter((j) => j.url !== saved.endpoint || j.model !== saved.model),
    ];
  $("judges").innerHTML = list
    .map(
      (j, i) =>
        `<article class="judge" data-label="${esc(j.label)}" data-url="${esc(j.url)}" data-local="${j.local}"><label><input data-enabled type="checkbox" ${(j.local && j.model) || (i === 0 && saved.configured && !settings.preferred_local_model) ? "checked" : ""}>${esc(j.label)}</label><span data-status class="pill">${j.credential_configured ? "Saved key · connection not checked" : "Not checked yet"}</span><details><summary>Model and API key</summary><div class="grid"><label>Model ID<input data-model list="models-${i}" value="${esc(j.model)}" placeholder="Enter a model available to your account"></label><label>API key (leave empty for saved or local)<input data-key type="password" autocomplete="off"></label></div><label ${j.local ? "" : "hidden"}><input data-fallback type="checkbox">Use only as a backup judge</label><button data-discover type="button">Show available models</button><datalist id="models-${i}">${j.local ? settings.ollama_models.map((m) => `<option value="${esc(m)}">`).join("") : ""}</datalist></details></article>`,
    )
    .join("");
  document.querySelectorAll(".judge").forEach((e) => {
    e.querySelector("[data-enabled]").onchange = () => {
      e.querySelector("details").open = e.querySelector("[data-enabled]").checked;
      syncSetup();
    };
    e.querySelector("[data-model]").oninput = syncSetup;
    e.querySelector("[data-fallback]").onchange = syncSetup;
    e.querySelector("[data-discover]").onclick = async () => {
      try {
        const result = await api("/api/studio/models", {
          model: "discovery",
          url: e.dataset.url,
          token: e.querySelector("[data-key]").value || null,
          local: e.dataset.local === "true",
        });
        e.querySelector("datalist").innerHTML = result.models
          .map((m) => `<option value="${esc(m)}">`)
          .join("");
        e.querySelector("[data-status]").textContent =
          result.models.length + " available models. Open the Model ID dropdown.";
      } catch (error) {
        e.querySelector("[data-status]").textContent = error.message;
      }
    };
  });
  $("local-models").innerHTML = settings.ollama_models
    .map((m) => `<option value="${esc(m)}">`)
    .join("");
  $("local-status").textContent = settings.ollama_models.length
    ? "Installed Ollama models: " + settings.ollama_models.join(", ")
    : "Ollama is unavailable or has no installed models. No automatic local fallback can run yet.";
  planned();
  $("judge-options").open = !judges().some((j) => !j.fallback);
  await loadHistory();
  await poll();
  $("start").disabled = false;
}
document.querySelectorAll("[data-mode]").forEach((e) => e.addEventListener("change", syncSetup));
$("add-bot").onclick = addBot;
$("start").onclick = async () => {
  try {
    const cfg = configuration();
    if (!cfg.judges.length) throw new Error("Choose a judge model first.");
    const result = await api("/api/studio/runs", cfg);
    runId = result.id;
    window.StudioUI.selectRun(runId, { notify: false });
    window.StudioUI.navigate("results");
    tell("Evaluation started. Each completed conversation is saved.");
    await poll();
    await loadHistory();
  } catch (error) {
    tell(error.message);
  }
};
$("apply-judges").onclick = async () => {
  try {
    await api(
      `/api/studio/runs/${runId}/judges`,
      { judges: judges(), consent: $("consent").checked },
      "PUT",
    );
    tell("Future cases use the updated judges; in-flight calls keep their original judge.");
  } catch (error) {
    tell(error.message);
  }
};
$("resume").onclick = async () => {
  try {
    const cards = [...document.querySelectorAll(".bot")];
    const sameTargets =
      current?.targets.length === cards.length &&
      cards.every(
        (card, index) =>
          card.querySelector("[data-field=url]").value.trim() === current.targets[index].url,
      );
    if (!sameTargets && current?.config.simple_mode) {
      hydrateRequested = true;
      render(current);
      window.StudioUI.navigate("evaluate");
      tell(
        "This run’s bot settings are loaded. Add any required keys, allow test access, then choose Resume missing cases.",
      );
      return;
    }
    await api(`/api/studio/runs/${runId}/resume`, {
      ownership_confirmed: $("ownership").checked,
      judges: judges(),
      consent: $("consent").checked,
      target_tokens: [...document.querySelectorAll(".bot")].map(
        (e) => e.querySelector("[data-field=token]").value || null,
      ),
    });
    tell("Resuming missing cases. Completed scores and costs remain recorded.");
    await poll();
  } catch (error) {
    tell(error.message);
  }
};
$("stop").onclick = async () => {
  try {
    await api(`/api/blackbox/runs/${runId}/stop`, {});
    await poll();
  } catch (error) {
    tell(error.message);
  }
};
$("references-file").onchange = async (e) => {
  try {
    $("references").value = await e.target.files[0].text();
    JSON.parse($("references").value);
  } catch (error) {
    tell("Invalid reference JSON: " + error.message);
  }
};
$("use-run-settings").onclick = () => {
  if (!current?.config.simple_mode) return;
  hydrateRequested = true;
  render(current);
  window.StudioUI.navigate("evaluate");
  tell("Saved settings loaded. Re-enter any required API keys; keys are not copied from reports.");
};
window.addEventListener("studio:run-selected", async (event) => {
  runId = event.detail.id;
  current = null;
  hydrateRequested = false;
  liveEvents?.close();
  liveRun = "";
  liveEvents = null;
  [
    "verdict",
    "scores",
    "bias-details",
    "integrity",
    "costs",
    "case-results",
    "audit",
    "downloads",
    "relevance-charts",
    "live-progress",
  ].forEach((id) => ($(id).innerHTML = ""));
  ["stop", "resume", "apply-judges", "use-run-settings"].forEach((id) => ($(id).disabled = true));
  $("progress").value = 0;
  $("stage").textContent = runId
    ? "Loading selected evaluation…"
    : "Choose a saved evaluation or start a new test.";
  if (settings && runId && resultCache.has(runId)) render(resultCache.get(runId));
  if (settings) await poll();
});
window.addEventListener("studio:history-refresh", () =>
  loadHistory().catch((error) => tell(error.message)),
);
window.addEventListener("studio:refresh", async () => {
  await poll();
  await loadHistory();
});
boot().catch((error) => tell(error.message));
setInterval(() => {
  if (current && ["queued", "running"].includes(current.status)) poll();
}, 2500);

let liveEvents = null;
let liveRun = "";
function renderGovernanceExtras(run) {
  const biasOpen = new Set(
    [...$("bias-details").querySelectorAll("details[open]")].map((d) => d.dataset.bias),
  );
  $("bias-details").innerHTML = (run.studio?.bots || [])
    .map(
      (bot) =>
        `<h3>${esc(bot.name)} — Bias sub-tests</h3>${(bot.bias_subtests || []).map((s) => `<details data-bias="${esc(bot.name + ":" + s.subtype)}" ${biasOpen.has(bot.name + ":" + s.subtype) ? "open" : ""}><summary>${esc(s.name || s.subtype)}: ${s.score}% • ${esc(s.status)} • severity ${esc(s.severity)}</summary><p>${esc(s.reason)}</p><div class="grid">${s.evidence.map((e) => `<article class="transcript"><strong>${esc(e.prompt)}</strong><p>${esc(e.excerpt)}</p></article>`).join("")}</div><small>${esc(s.signals?.limitation || (s.subtype === "algorithmic" ? "Derived aggregate; source pairs are linked in the JSON." : "No screening signals were recorded for this historical result."))}</small></details>`).join("")}`,
    )
    .join("");
  const overrides = run.cases.flatMap((c) => c.results).filter((r) => r.human_review_note).length;
  $("integrity").innerHTML =
    `<p class="integrity-note">${run.cases.filter((c) => c.completed).length}/${run.cases.length} records processed · ${overrides} overrides · Judge agreement: ${run.studio?.agreement_percent == null ? "Not measured" : run.studio.agreement_percent + "%"}. <a href="#governance" data-view="governance">View trust &amp; history →</a></p>`;
  if (liveRun !== run.id) {
    liveEvents?.close();
    liveRun = run.id;
    const source = new EventSource(`/api/studio/runs/${run.id}/events`);
    liveEvents = source;
    source.onmessage = (event) => {
      if (run.id !== runId) return;
      const data = JSON.parse(event.data);
      $("live-progress").innerHTML =
        `<p>Active run time: ${data.active_seconds}s. Bot time sums exclude queueing; concurrent work overlaps.</p>` +
        table(
          ["Bot", "Category", "Processed / planned", "Scored", "Bot seconds", "Case work seconds"],
          data.bots.flatMap((b) =>
            b.categories.map((c) => [
              esc(b.name),
              esc(c.category),
              `${c.processed}/${c.planned}`,
              c.scored,
              c.bot_seconds,
              c.case_work_seconds,
            ]),
          ),
        );
      if (!["running", "queued"].includes(data.status)) {
        source.close();
        liveRun = "";
      }
    };
  }
}
