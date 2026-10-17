// Visible controls. Credentials remain in password inputs and request memory only.
const controlPanel = document.createElement("section");
controlPanel.className = "card";
controlPanel.id = "run-controls";
controlPanel.innerHTML = `<h2>Tests, API provider and recovery</h2>
<p>Select the checks you want below. Change the judge here if its quota runs out. Your chatbot's own provider is configured separately.</p>
<div class="actions"><button id="select-all-tests">Select all tests</button><button id="clear-tests">Clear selection</button><button id="load-reliance-20">Load Reliance: 20 per category</button><button id="load-reliance-pack">Load Reliance 509-case pack</button></div>
<div id="visible-tests"></div><div id="visible-import"></div>
<label><input type="checkbox" id="all-imports" checked>Run every imported case (ignore per-category cap for imports)</label>
<h3>AI judge provider</h3><label>Provider<select id="judge-provider"><option value="saved">Saved backend judge</option><option value="openai">OpenAI</option><option value="gemini">Gemini (Google)</option><option value="gemma">Gemma (Google API)</option><option value="kimi">Kimi (Moonshot)</option><option value="deepseek">DeepSeek</option><option value="custom">Custom / local compatible API</option></select></label>
<div id="visible-judge" class="columns"></div>
<p class="help">Enter a model supported by your account and its provider API key. Keys are not stored in browser storage or reports. Changing provider requires renewed data-sharing consent.</p>
<div id="visible-budget"></div>
<label><input id="quota-mode" type="checkbox">Slow quota mode: one case at a time, 30 seconds between bot/judge requests</label>
<p class="help">Use this for short-term rate limits. It cannot bypass exhausted daily quotas or missing API balance. Large suites can take several hours. Stop a run before changing its pace.</p>
<button id="resume-pending">Resume pending cases with this judge</button>
<p>Stop a running evaluation before switching. Completed scores and transcripts are retained. If the judge changes, the report records mixed-judge results. Unknown billing stays unknown, even with no budget cap.</p>
<p id="recovery-status" role="status"></p>`;
$("setup").insertBefore(controlPanel, $("advanced"));
$("visible-tests").append($("categories").closest("details"));
$("categories").closest("details").open = true;
$("visible-import").append($("case-set-file").closest("details"));
for (const id of ["judge-url", "judge-model", "judge-token"])
  $("visible-judge").append($(id).closest("label"));
$("visible-budget").append($("cost-budget").closest("label"));
const providers = {
  openai: "https://api.openai.com/v1/chat/completions",
  gemini: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
  gemma: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
  kimi: "https://api.moonshot.ai/v1/chat/completions",
  deepseek: "https://api.deepseek.com/chat/completions",
};
$("judge-provider").onchange = () => {
  const provider = $("judge-provider").value;
  $("judge-token").value = "";
  $("judge-model").value = provider === "gemma" ? "gemma-4-26b-a4b-it" : "";
  $("judge-url").value = providers[provider] || "";
  $("cost-judge-alias").value = "";
  $("judge-consent").checked = false;
  $("judge-url").dispatchEvent(new Event("input"));
};
$("select-all-tests").onclick = () => {
  document.querySelectorAll("#categories input").forEach((x) => (x.checked = true));
  planned();
};
$("clear-tests").onclick = () => {
  document.querySelectorAll("#categories input").forEach((x) => (x.checked = false));
  planned();
};
$("load-reliance-pack").onclick = async () => {
  try {
    const data = await api("/api/blackbox/case-set/reliance-expanded");
    importedCases = data.cases;
    $("case-set-status").textContent =
      `Loaded ${importedCases.length} cases, including 49 user-added hallucination cases and 10 mock-catalogue functional checks. Includes labelled template variations.`;
    $("url-0").value = "http://127.0.0.1:8000/chat/stream";
    $("kind-0").value = "rest";
    $("name-0").value = "Reliance Gemini";
    $("response-0").value = "reply";
    $("session-0").value = "";
    $("history-0").value = "history";
    $("defaults-0").value = '{"provider":"gemini"}';
    $("model-0").value = data.target_model;
    $("cost-model-0").value = data.target_model;
    $("all-imports").checked = true;
    $("select-all-tests").click();
    $("evaluation-method").value = "combined";
    planned();
  } catch (error) {
    notice(error.message);
  }
};
$("resume-pending").onclick = async () => {
  try {
    if (!current) throw new Error("Open a saved result first.");
    if (["running", "queued"].includes(current.status))
      throw new Error("Stop this run first and wait until it stops.");
    if (!$("judge-consent").checked) throw new Error("Enable AI judge data-sharing consent.");
    const config = structuredClone(current.config);
    config.targets = current.targets.map((t, i) => ({
      ...t,
      token: $(`token-${i}`)?.value || null,
    }));
    config.judge_model =
      $("judge-model").value.trim() ||
      ($("judge-provider").value === "saved" ? savedJudge.model : current.config.judge_model);
    config.judge_url =
      $("judge-url").value.trim() ||
      ($("judge-provider").value === "saved" ? savedJudge.endpoint : current.config.judge_url);
    config.judge_token = $("judge-token").value || null;
    config.judge_model_alias = $("cost-judge-alias").value.trim() || config.judge_model;
    config.judge_consent = true;
    config.max_budget_usd = $("cost-budget").value || null;
    config.timeout = Number($("timeout").value);
    config.max_minutes = Number($("minutes").value);
    if ($("quota-mode").checked) {
      Object.assign(config, {
        case_concurrency: 1,
        target_concurrency: 1,
        judge_concurrency: 1,
        request_pause_seconds: 30,
        judge_pause_seconds: 30,
        max_minutes: 720,
      });
    }
    if (
      !confirm(
        `Resume only missing cases using ${config.judge_model}? Completed cases are retained. Budget: ${config.max_budget_usd || "no dollar cap"}.`,
      )
    )
      return;
    const result = await api(`/api/blackbox/runs/${current.id}/resume`, {
      method: "POST",
      body: JSON.stringify(config),
    });
    $("recovery-status").textContent = `Resuming ${result.pending_cases} pending cases.`;
    await load(current.id);
  } catch (error) {
    notice(error.message);
  }
};
// Delete only the individual run explicitly selected by the user.
$("history-panel").addEventListener("click", async (e) => {
  const button = e.target.closest("[data-delete-run]");
  if (!button) return;
  if (
    !confirm(
      "Permanently delete this selected run and its saved token/cost records? Other runs are kept. Downloaded reports are unchanged.",
    )
  )
    return;
  try {
    await api(`/api/blackbox/runs/${button.dataset.deleteRun}`, { method: "DELETE" });
    if (current?.id === button.dataset.deleteRun) {
      clearTimeout(poll);
      current = null;
    }
    $("history").click();
    notice("Selected run deleted. Other runs were kept.");
  } catch (error) {
    notice(error.message);
  }
});

$("all-imports").addEventListener("change", planned);

$("quota-mode").onchange = () => {
  if ($("quota-mode").checked) {
    for (const id of ["case-concurrency", "target-concurrency", "judge-concurrency"])
      $(id).value = 1;
    $("target-pause").value = 30;
    $("judge-pause").value = 30;
    $("minutes").value = 720;
  }
};

$("load-reliance-20").onclick = async () => {
  try {
    const data = await api("/api/blackbox/case-set/reliance-20");
    importedCases = data.cases;
    $("case-set-status").textContent =
      "320 cases: 20 per category, including 10 uploaded hallucination cases. Some cases are labelled template variations.";
    $("url-0").value = "http://127.0.0.1:8000/chat/stream";
    $("kind-0").value = "rest";
    $("name-0").value = "Reliance with Gemma 4";
    $("response-0").value = "reply";
    $("session-0").value = "";
    $("history-0").value = "history";
    $("defaults-0").value = '{"provider":"gemma"}';
    $("model-0").value = data.target_model;
    $("cost-model-0").value = data.target_model;
    $("count").value = 20;
    $("all-imports").checked = true;
    $("select-all-tests").click();
    planned();
  } catch (error) {
    notice(error.message);
  }
};
