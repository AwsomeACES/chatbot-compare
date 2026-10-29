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
    scenario_suite: $("scenario-suite")?.value || "",
    repeat_counts: Object.fromEntries(
      [...document.querySelectorAll("[data-repeat]")].map((e) => [
        e.dataset.repeat,
        Number(e.value),
      ]),
    ),
    references: JSON.parse($("references").value || "[]"),
    reference_profile: declaredProfile(),
    policy: $("policy").value,
    scope: $("scope").value,
    ...settings.execution,
    retention_days: Number($("retention").value),
  };
}
const money = (n, local = false) => {
  if (n == null) return window.StudioStatus.QUALIFIER.unknown;
  if (n === 0 && local) return "$0 (local)";
  return n > 0 && n < 100 ? "<$0.0001" : "$" + (n / 1000000).toFixed(6);
};
const costMoney = (row) => {
  if (row?.cost_micro_usd == null) {
    const unknown = window.StudioStatus.QUALIFIER.unknown;
    return row?.known_cost_micro_usd == null
      ? unknown
      : `${money(row.known_cost_micro_usd)} known subtotal <small>Total ${unknown.toLowerCase()} — some charges are missing.</small>`;
  }
  return row?.cost_micro_usd != null &&
    Number(row.exact_micro_usd) > 0 &&
    Number(row.exact_micro_usd) < 100
    ? "<$0.0001"
    : money(row?.cost_micro_usd, row?.calls > 0 && row.local_calls === row.calls);
};
function table(head, rows) {
  return `<div class="scroll"><table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function bar(value, max) {
  return `<div class="bar-track"><div class="bar" style="width:${Math.min(100, Math.max(0, (Number(value) / Math.max(1, max)) * 100))}%"></div></div>`;
}
/* Whether the loaded detail for the selected run disagrees with the status the history list
   reports. An externally resumed Run (a recovery script, or a second window) changes the list
   while the loaded snapshot keeps its old status, and the fast heartbeat below only polls while
   the loaded status is active. */
/* The owner's declared facts and capabilities, or null when nothing was declared. Each line is
   one declaration; the backend refuses a source-derived declaration without the approval box. */
function declaredLines(id) {
  return ($(id).value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}
function declaredProfile() {
  const facts = declaredLines("declared-facts");
  const capabilities = declaredLines("declared-capabilities");
  if (!facts.length && !capabilities.length) return null;
  const fromSource = $("declared-from-source").checked;
  return {
    general_facts: facts,
    capabilities,
    provenance: {
      supplied_by: $("declared-by").value.trim() || "Not stated",
      supplied_at: new Date().toISOString(),
      source: $("declared-source").value.trim() || "Not stated",
      source_derived: fromSource,
      owner_approved: fromSource,
    },
  };
}
function staleAgainstHistory(runs, id, loaded) {
  if (!id || !loaded || loaded.id !== id) return false;
  const listed = (runs || []).find((r) => r && r.id === id);
  return Boolean(listed && listed.status !== loaded.status);
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
    const declared = run.config.reference_profile;
    $("declared-facts").value = (declared?.general_facts || []).join("\n");
    $("declared-capabilities").value = (declared?.capabilities || []).join("\n");
    $("declared-by").value = declared?.provenance?.supplied_by || "";
    $("declared-source").value = declared?.provenance?.source || "";
    $("declared-from-source").checked = Boolean(declared?.provenance?.source_derived);
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
  const resultCases = studio
    ? run.protocol_snapshot?.cases ||
      settings.cases.filter((c) => run.categories.includes(c.category))
    : [...new Set(run.cases.map((c) => c.category))].map((category) => ({
        category,
        name: run.summary?.[0]?.categories?.find((c) => c.id === category)?.name || category,
      }));
  const caseName = (item) =>
    studio
      ? settings.cases.find((c) => c.category === item.category)?.name || item.name
      : item.name;
  if (!studio) {
    // Display the saved summary without converting it to the newer scoring protocol.
    $("verdict").innerHTML =
      `<details class="subtle-details"><summary>Saved evaluation results — scoring details</summary><p>Run ${esc(run.id)} · ${esc(run.status)}. Original scoring rules are preserved. Not tested means missing evidence, not a failed answer.</p><p>${esc(run.score_formula || "Quality and coverage are reported separately.")}</p></details>${verdictConsistency()}${evaluatorProvenance()}${panelPolicy()}`;
    $("scores").innerHTML = (run.targets || [])
      .map((target, index) => {
        const summary = run.summary?.[index];
        if (!summary)
          return `<article class="metric"><h3>${esc(target.name)}</h3><p>Summary unavailable. See the saved case evidence below.</p></article>`;
        const outcomes = run.cases.map((c) => c.results[index]).filter(Boolean);
        const passed = outcomes.filter((r) => r.status === "passed").length;
        const failed = outcomes.filter((r) => r.status === "failed").length;
        const missing = outcomes.filter((r) => r.status === "not_tested").length;
        return `<article class="metric"><h3>${esc(target.name)}</h3><p>Measured quality</p><div class="score">${summary.score == null ? "Not measured" : esc(summary.score) + "/100"}</div><p>${esc(summary.tested)}/${esc(summary.total)} outcomes scored · ${esc(summary.coverage)}% coverage</p><p>${passed} passed · ${failed} failed · ${missing} Not tested</p><p>${esc(summary.verdict)}</p>${table(
          ["Category", "Measured quality", "Scored / planned", "Coverage"],
          (summary.categories || []).map((c) => [
            esc(c.name || c.id),
            c.score == null ? "Not measured" : `${esc(c.score)}% ${bar(c.score, 100)}`,
            `${esc(c.tested)}/${esc(c.total)}`,
            `${esc(c.coverage)}%`,
          ]),
        )}</article>`;
      })
      .join("");
    $("relevance-charts").hidden = true;
    $("relevance-charts").innerHTML = "";
  } else {
    $("verdict").innerHTML =
      `<div class="verdict-card"><h3>${studio.winner == null ? (studio.bots.length === 1 ? "Evaluation summary" : "Comparison summary") : "Winner: " + esc(run.targets[studio.winner].name)}</h3><p>${esc(studio.confidence_note)}</p>${generalWarnings(studio).length ? `<p class="unknown">${generalWarnings(studio).map(esc).join(" ")}</p>` : ""}${familyWarnings(studio)}</div>${verdictConsistency()}${evaluatorProvenance()}${panelPolicy()}<details class="subtle-details"><summary>How to read these scores</summary><p>${esc(studio.formula)}</p><p>Not tested is missing evidence, not a failed answer. It contributes zero to this evaluation index. Measured quality and coverage are shown separately.</p></details>`;
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
            `<article class="metric"><h3>${esc(b.name)}</h3><span class="pill">${b.tested === b.planned ? "Fully scored" : "Partial coverage"}</span><p class="muted">Overall score</p><div class="score">${b.score}<small>/100</small></div><p><strong>${b.tested}/${b.planned}</strong> outcomes scored · ${b.planned ? Math.round((100 * b.tested) / b.planned) : 0}% coverage</p><p>Strongest measured check: ${esc([...b.categories].filter((c) => c.tested).sort((a, z) => z.quality - a.quality)[0]?.name || "Not established")}<br>Lowest measured category scores: ${esc(
              [...b.categories]
                .filter((c) => c.tested)
                .sort((a, z) => a.score - z.score)
                .slice(0, 3)
                .map((c) => c.name)
                .join(", ") || "None measured",
            )}${
              /* An unmeasured category has no score to be lowest. Listing it beside the weakest
                 measured ones would present missing evidence as a demonstrated weakness. */
              [...b.categories].some((c) => !c.tested)
                ? `<br><span class="muted">Not tested (no measurement, not a weakness): ${esc(
                    [...b.categories]
                      .filter((c) => !c.tested)
                      .map((c) => c.name)
                      .join(", "),
                  )}</span>`
                : ""
            }</p>${bar(b.score, 100)}</article>`,
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
                `${g.low_confidence ? '<span class="pill">Low confidence</span> ' : ""}${g.score}% ${bar(g.score, 100)}<small>${g.tested}/${g.planned} scored; measured quality: ${g.quality == null ? window.StudioStatus.QUALIFIER.not_measured : g.quality + "%"}; largest within-case repeat spread: ${g.repeat_spread ?? g.spread ?? "Unknown"} points</small>`,
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
  }
  const costs = run.costs;
  if (costs?.available) {
    const rows = [
      ...(costs.bots || []).map((b) => ({ ...b, label: "Bot: " + b.name })),
      ...(costs.breakdowns?.model_alias || [])
        .filter((b) => b.evaluation?.calls)
        .map((b) => ({ ...b.evaluation, label: "Judge: " + b.name })),
    ];
    const max = Math.max(1, ...rows.map((r) => r.input_tokens + r.output_tokens));
    const chartCost = (r) => r.cost_micro_usd ?? r.known_cost_micro_usd;
    const maxCost = Math.max(1, ...rows.map((r) => chartCost(r) || 0));
    $("costs").innerHTML =
      '<div class="cost-summary"><span>Bot cost <strong>' +
      costMoney(costs.bot) +
      `</strong><small>${costs.bot.input_tokens.toLocaleString()} input / ${costs.bot.output_tokens.toLocaleString()} output tokens</small></span><span>Judge cost <strong>` +
      costMoney(costs.evaluation) +
      `</strong><small>${costs.evaluation.input_tokens.toLocaleString()} input / ${costs.evaluation.output_tokens.toLocaleString()} output tokens</small></span></div>` +
      "<h3>Usage by bot and judge</h3>" +
      table(
        ["Bot / judge", "Tokens (input / output)", "USD cost / known subtotal"],
        rows.map((r) => [
          esc(r.label),
          `${r.input_tokens.toLocaleString()} / ${r.output_tokens.toLocaleString()}${bar(r.input_tokens + r.output_tokens, max)}`,
          costMoney(r) + (chartCost(r) == null ? "" : bar(chartCost(r), maxCost)),
        ]),
      ) +
      '<p class="helper">Dollar amounts use this run’s saved prices, not a provider invoice. Known subtotals exclude missing charges. Token totals may include estimates; hidden bot calls need the bot’s own usage reporting. Reasoning tokens are already included in output.</p>';
  } else
    $("costs").innerHTML =
      '<p class="empty-state">Cost is unavailable for this run. Missing usage is never treated as free.</p>';
  const openIds = new Set(
    [...document.querySelectorAll("#case-results details[open]")].map((e) => e.dataset.case),
  );

  /* ---- evaluator provenance: who actually scored each Case ---- */

  function judgeProvenance(verdict) {
    // A verdict saved before provenance recording says so; nothing is reconstructed.
    if (!verdict || verdict.provenance_version == null)
      return `<br><small class="provenance">Evaluator provenance unavailable for this saved result.</small>`;
    const parts = [];
    if (verdict.requested_model && verdict.requested_model !== verdict.model)
      parts.push(`requested ${esc(verdict.requested_model)}`);
    parts.push(`${esc(verdict.provider || "unknown provider")}${verdict.local ? ", local" : ""}`);
    parts.push(`returned ${esc(verdict.provider_model || "Not supplied by provider")}`);
    if (verdict.family) parts.push(`family ${esc(verdict.family)}`);
    const why = (verdict.fallback_reasons || [])
      .map((row) => `${esc(row.model)}: ${esc(row.reason)}`)
      .join("; ");
    /* A local fallback runs on this machine: it is slower than a hosted judge and its API fee
       is zero while the hardware cost is excluded. Saying so explains a slow run. */
    const slow = verdict.local
      ? " Runs on this machine, so it is slower than a hosted judge; its API fee is zero and hardware cost is excluded."
      : "";
    const fallback = verdict.fallback
      ? `<br><small class="provenance">Fallback evaluator. ${why ? `Requested judge unavailable — ${why}` : "Reason not recorded."}${slow}</small>`
      : "";
    return `<br><small class="provenance">Actual evaluator: ${parts.join(" · ")}. Returned names are not guaranteed immutable revisions.</small>${fallback}`;
  }

  function nonJudgeEngine(result) {
    if (!result || (result.judges || []).length) return "";
    const engine = result.engine || "";
    if (!engine) return "";
    const label = result.local_classifier
      ? "Local classifier, no LLM judge"
      : engine === "deterministic-text"
        ? "Deterministic rule, no LLM judge"
        : engine === "measured-latency"
          ? "Measured latency, no LLM judge"
          : `${engine}, no LLM judge`;
    return `<p class="judge-reason"><small class="provenance">${esc(label)}.</small></p>`;
  }

  function familyWarnings(studio) {
    const rows = studio.family_warnings || [];
    if (!rows.length) return "";
    return `<p class="unknown" data-family-warning>${rows.map(esc).join(" ")} This is separate from human calibration and from model-to-model judge agreement.</p>`;
  }

  function generalWarnings(studio) {
    // Same-family warnings render in their own block, so they are not repeated here.
    const family = new Set(studio.family_warnings || []);
    return (studio.warnings || []).filter((warning) => !family.has(warning));
  }

  function evaluatorProvenance() {
    const info = run.judge_provenance;
    if (!info) return "";
    const rows = (info.evaluators || [])
      .map((e) => {
        const calibration = e.calibration
          ? `${esc(e.calibration.state)}${e.calibration.agreement_percent == null ? "" : ` (${esc(e.calibration.agreement_percent)}%)`}`
          : "unavailable";
        return `<tr><td>${esc(e.actual_model)}</td><td>${esc((e.requested_models || []).join(", ") || "Not recorded")}</td><td>${esc(e.provider)}${e.local === true ? " (local)" : e.local === null ? "" : ""}</td><td>${esc((e.returned_models || []).join(", "))}</td><td>${e.fallback_cases ? `${esc(e.fallback_cases)} case(s)` : "No"}</td><td>${calibration}</td></tr>`;
      })
      .join("");
    const engines = Object.entries(info.non_judge_engines || {})
      .map(([label, count]) => `<li>${esc(label)}: ${esc(count)} result(s)</li>`)
      .join("");
    const unavailable = info.unavailable_note
      ? `<p class="unknown">${esc(info.unavailable_note)}</p>`
      : "";
    const mixed = info.mixed_note ? `<p class="unknown">${esc(info.mixed_note)}</p>` : "";
    return `<details class="subtle-details" id="evaluator-provenance"><summary>Which judge scored these cases</summary>${mixed}${unavailable}${rows ? `<table class="cal-table"><thead><tr><th>Actual evaluator</th><th>Requested</th><th>Provider</th><th>Returned identifier</th><th>Fallback</th><th>Human calibration</th></tr></thead><tbody>${rows}</tbody></table>` : `<p class="helper">No LLM judge verdict is recorded for this test.</p>`}${engines ? `<ul>${engines}</ul>` : ""}<p class="helper">${esc(info.revision_note)} ${esc(info.calibration_note)}</p></details>`;
  }

  /* A score that contradicts its own explanation is unreliable evidence for either outcome, so
     it is named where the evidence is read rather than left to look like a measured failure. */
  function consistencyNotice(result) {
    const rows = result.contradictions || [];
    if (result.consistency_status !== "contradictory" && !rows.length) return "";
    const label =
      result.consistency_status === "contradictory"
        ? window.StudioStatus.QUALIFIER.contradictory
        : window.StudioStatus.QUALIFIER.mixed_panel;
    const explain =
      result.consistency_status === "contradictory"
        ? window.StudioStatus.EXPLAIN.contradictory
        : window.StudioStatus.EXPLAIN.mixed_panel;
    const detail = rows.map((row) => `${row.model}: ${row.detail}`).join(" ");
    return `<p class="unknown"><strong>${esc(label)}</strong> ${esc(explain)}${
      detail ? " " + esc(detail) : ""
    } Next action: read the retained judge output below, then record a human review.</p>`;
  }

  /* Per-judge consistency, so a mixed panel shows which member contradicted itself. */
  function judgeConsistency(judge) {
    const state = judge.consistency?.status;
    if (!state || state === "consistent") return "";
    if (state === "contradictory")
      return ` <span class="pill">${esc(window.StudioStatus.QUALIFIER.contradictory)}</span><br><small>${esc(judge.consistency.detail || "")}</small>`;
    return ` <span class="pill">${esc(window.StudioStatus.QUALIFIER.not_measured)}: no verdict word was returned, so agreement was not established</span>`;
  }

  /* Contradictions found by reading the saved verdicts. Shown for review beside the scores; no
     stored score, status or reason is changed by it. */
  function verdictConsistency() {
    const info = run.verdict_consistency;
    if (!info) return "";
    const rows = (info.contradictions || [])
      .map(
        (row) =>
          `<tr><td>${esc(row.case)}</td><td>${esc(run.targets[row.bot]?.name || "Bot " + (row.bot + 1))}</td><td>${esc(row.model)}</td><td>${esc(row.score)}</td><td>${esc(row.detail)}</td></tr>`,
      )
      .join("");
    const summary = rows
      ? `${info.contradictions.length} saved ${window.StudioStatus.QUALIFIER.contradictory.toLowerCase()} — review before relying on these results`
      : "Saved verdict consistency review — none found";
    return `<details class="subtle-details" id="verdict-consistency"${rows ? " open" : ""}><summary>${esc(summary)}</summary>${
      rows
        ? `<p class="unknown">${esc(window.StudioStatus.EXPLAIN.contradictory)}</p><table class="cal-table"><thead><tr><th>Case</th><th>Bot</th><th>Judge</th><th>Saved score</th><th>Why it contradicts</th></tr></thead><tbody>${rows}</tbody></table><p>Next action: open each case below, read the retained judge output, then record a human review. Re-judging produces a separately identifiable evaluation.</p>`
        : `<p class="helper">No saved verdict was found whose score contradicts its own explanation.</p>`
    }<p class="helper">${esc(info.note)} ${esc(info.coverage_note)}</p></details>`;
  }

  /* Providers that failed on this Case, with the condition and the action it implies. Recorded
     per result by the panel; an account or billing problem is not a chatbot defect. */
  function judgeFailures(result) {
    const rows = (result?.judge_failures || []).filter(Boolean);
    if (!rows.length) return "";
    const items = rows
      .map((row) => {
        const label = row.label || window.StudioStatus.label(row.state || "unknown");
        const waiting = row.retryable === false ? " Waiting will not resolve this." : "";
        const status = row.http_status ? ` HTTP ${esc(row.http_status)}.` : "";
        return `<li><strong>${esc(row.model || "Judge")}: ${esc(label)}.</strong>${status} ${esc(row.reason || "")}${esc(waiting)}${row.action ? ` <em>Next action: ${esc(row.action)}</em>` : ""}</li>`;
      })
      .join("");
    return `<div class="unknown"><p><strong>Judges that did not produce a verdict here</strong></p><ul>${items}</ul></div>`;
  }

  /* What the panel was allowed to do, stated rather than inferred from which judges appear. */
  function panelPolicy() {
    const policy = run.judge_policy;
    if (!policy) return "";
    const requested =
      (policy.requested_judges || [])
        .map((j) => `${esc(j.model)}${j.local ? " (local)" : ""}`)
        .join(", ") || "none recorded";
    const fallbacks =
      (policy.declared_fallbacks || [])
        .map((j) => `${esc(j.model)}${j.local ? " (local)" : ""}`)
        .join(", ") || "none declared";
    const rules = (policy.rules || []).map((rule) => `<li>${esc(rule)}</li>`).join("");
    return `<details class="subtle-details" id="judge-policy"><summary>Which judges were allowed, and what happens when one fails</summary><p>Requested judges: ${requested}. Declared fallbacks: ${fallbacks}. Automatic local fallback: ${policy.automatic_local_fallback ? "on" : "off"}.</p><ul>${rules}</ul><p class="helper">${esc(policy.discovery_note || "")}</p></details>`;
  }

  function caseEvidence(category) {
    return run.cases
      .filter((c) => c.category === category)
      .map(
        (c) =>
          `<div class="case-evidence"><h4>${esc(c.name)} · case ${c.scenario_index || 1}, repeat ${c.repeat ?? 1}</h4><div class="grid">${c.results
            .map(
              (r, i) =>
                `<article><strong>${esc(run.targets[i].name)} <span class="pill">${esc(window.StudioStatus.label(r.status))}</span></strong><p>Score: ${r.score == null ? `${window.StudioStatus.RESULT.not_tested}${studio ? " (index contribution 0)" : " (excluded from measured quality)"}` : r.score + "/100"}</p><p>${r.human_review_note ? "<strong class=badge>Overridden — reason logged</strong> " : ""}${r.needs_review ? `<strong>${esc(window.StudioStatus.QUALIFIER.needs_review)}</strong> ` : ""}${esc(r.reason)}</p>${consistencyNotice(r)}${(r.judges || []).map((j) => `<p class="judge-reason">Judge: ${esc(j.model)} — ${j.score}%${judgeConsistency(j)}<br>Evidence: ${j.evidence.map(esc).join(" | ")}${judgeProvenance(j)}</p>`).join("")}${judgeFailures(r)}${nonJudgeEngine(r)}${window.renderEvidenceDetails(c, r)}${r.transcript
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
      const passed = rows.filter((r) => r.status === "passed").length;
      const untested = rows.filter((r) => r.status === "not_tested").length;
      const contradicted = rows.filter(
        (r) => r.consistency_status === "contradictory" || (r.contradictions || []).length,
      ).length;
      const meta =
        `${rows.length} processed · ${scored} scored · ${passed} passed · ${untested} ${window.StudioStatus.RESULT.not_tested}` +
        (contradicted ? ` · ${contradicted} ${window.StudioStatus.QUALIFIER.contradictory}` : "");
      return `<details data-case="${esc(item.category)}" ${openIds.has(item.category) ? "open" : ""}><summary>${esc(caseName(item))}<span class="summary-meta">${esc(meta)}</span></summary><div data-case-body>${openIds.has(item.category) ? caseEvidence(item.category) : ""}</div></details>`;
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
  const savedAgreement = !studio
    ? table(
        ["Bot", "Model-to-model agreement", "Judged sample"],
        (run.judge_agreement || []).map((a) => [
          esc(a.target),
          a.agreement_percent == null ? "Not measured" : esc(a.agreement_percent) + "%",
          esc(a.judged),
        ]),
      )
    : "";
  $("audit").innerHTML =
    savedAgreement +
    `<p>Run ID: ${esc(run.id)}. Agreement measured on ${studio?.agreement_cases || 0} conversations with distinct valid judge models. Agreement: ${studio?.agreement_percent == null ? "Not measured" : studio.agreement_percent + "%"}. ${esc(studio?.agreement_definition || "")}</p><pre>${esc(JSON.stringify(run.audit || [], null, 2))}</pre>`;
  $("bias-panel").hidden = !studio?.bots.some((b) => b.bias_subtests?.length);
  renderGovernanceExtras(run);
  window.renderResultAnalysis(run);
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
  /* A Run resumed or stopped outside this page (by a recovery script, or a second window)
     reports its new status in this list while the selected result still holds the old
     snapshot. The heartbeat below only polls while the *loaded* status is active, so without
     this reconciliation the panel stayed stale until Refresh was pressed. */
  if (staleAgainstHistory(runs, runId, current)) await poll();
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
/* ---- scenario suites: the default stays the light screening set ---- */

function suiteSummary() {
  const summaries = settings.scenario_suite_summaries || {};
  return summaries[$("scenario-suite")?.value] || summaries[settings.default_scenario_suite] || {};
}

function renderSuites() {
  const select = $("scenario-suite");
  const summaries = settings.scenario_suite_summaries || {};
  if (!select || !Object.keys(summaries).length) return;
  const chosen = settings.default_scenario_suite || Object.keys(summaries)[0];
  select.innerHTML = Object.entries(summaries)
    .map(
      ([name, row]) =>
        `<option value="${esc(name)}"${name === chosen ? " selected" : ""}>${esc(row.label)} — ${esc(row.distinct_scenarios)} distinct scenarios</option>`,
    )
    .join("");
  select.onchange = () => {
    renderChecks();
    renderSuiteNote();
    planned();
  };
  renderSuiteNote();
}

function renderSuiteNote() {
  const row = suiteSummary();
  const review = row.review || {};
  const note = $("scenario-suite-note");
  if (!note) return;
  const reviewed = review.independently_reviewed
    ? "Independently reviewed."
    : "Authored, not independently reviewed.";
  note.textContent =
    `${row.note || ""} ${reviewed} ${row.distinct_scenarios || 0} distinct scenarios; repeats of one scenario are not extra coverage. ` +
    `Protocol version ${row.protocol_version || "unknown"}. More scenarios reduce the chance of missing a known failure mode; they do not show that a bot is safe.`;
}

function renderChecks() {
  const counts = suiteSummary().scenarios_per_category || {};
  $("checks").innerHTML = settings.cases
    .map(
      (c) =>
        `<label class="check">${esc(c.name)}<br><small>${esc(settings.descriptions?.[c.category] || "")}</small><br><small>${esc(counts[c.category] || settings.scenario_sets?.[c.category]?.length || 1)} distinct cases × repeats per case</small><br>Repeats <input type="number" min="1" max="20" value="${settings.default_repeats}" data-repeat="${c.category}"></label>`,
    )
    .join("");
  document.querySelectorAll("[data-repeat]").forEach((e) => (e.oninput = planned));
}

async function boot() {
  settings = await api("/api/studio/settings");
  $("suite-intro").textContent =
    `${settings.cases.length} categories cover accuracy, safety, fairness and helpfulness.`;
  addBot();
  $("test-preview").innerHTML = settings.cases.map((c) => `<span>${esc(c.name)}</span>`).join("");
  renderSuites();
  renderChecks();
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
    "analysis-summary",
    "charts",
    "cost-panel",
    "comparison",
    "judge-agreement",
    "regressions",
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
/* While the loaded result looks finished, re-read the history list at a slower cadence so an
   externally resumed Run is picked up without polling a completed result every few seconds. */
setInterval(() => {
  if (!runId || (current && ["queued", "running"].includes(current.status))) return;
  loadHistory().catch(() => {});
}, 10000);

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
