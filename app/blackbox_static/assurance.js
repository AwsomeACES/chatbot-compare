/* Evidence-mode controller. Keys remain in password fields and requests only. */
(() => {
  let id = new URLSearchParams(location.search).get("assessment"),
    current,
    busy = false,
    tab = "combined";
  let requestController,
    requestId,
    generation = 0;
  const resultCache = new Map();
  const root = $("assurance-results"),
    cards = new Map();
  const kinds = {
    system_prompt: "System prompt (.txt)",
    config: "Configuration (.json/.yaml)",
    tools: "Tools (.json)",
    knowledge: "Knowledge (.txt/.md)",
    logs: "Logs / OTel (.json/.jsonl)",
    code: "Source (.zip)",
  };
  const modeNames = {
    black: "Black-box testing",
    gray: "Gray-box testing",
    white: "White-box testing",
  };
  const resultNames = {
    pass: "Passed",
    fail: "Needs attention",
    not_tested: "Not tested",
    exists: "Found in code",
  };
  const friendly = (value) => String(value).replaceAll("_", " ");
  const genericFix = "Supply the missing input or install the named tool, then rerun this check.";
  const readinessClass = {
    ready: "ok",
    needs_input: "warn",
    tool_unavailable: "warn",
    not_applicable: "muted",
  };
  function renderReadiness(report) {
    const counts = report.counts || {};
    const labels = {
      ready: "Ready",
      needs_input: "Needs input",
      tool_unavailable: "Tool unavailable",
      not_applicable: "Not applicable",
    };
    const summary = Object.entries(labels)
      .map(([key, label]) => `${esc(label)}: ${Number(counts[key] || 0)}`)
      .join(" · ");
    const names = [...document.querySelectorAll(".bot")].map(
      (card, index) => card.querySelector('[data-field="name"]')?.value || `Bot ${index + 1}`,
    );
    $("readiness-results").innerHTML = report.error
      ? `<p>Readiness could not be checked (${esc(report.error)}). You can still start the test.</p>`
      : `<p><strong>${summary}</strong></p><p class="helper">${esc(report.notice)}</p>${table(
          ["Bot", "Testing type", "Check", "Status", "Why", "Next step"],
          report.checks.map((row) => [
            esc(names[row.bot] || `Bot ${row.bot + 1}`),
            esc(modeNames[row.mode] || row.mode),
            esc(row.title),
            `<span class="readiness-${readinessClass[row.status] || "muted"}">${esc(row.status_label)}</span>`,
            esc(row.reason) +
              (row.best_outcome ? `<br><small>${esc(row.best_outcome)}</small>` : ""),
            esc(row.next_action),
          ]),
        )}`;
  }
  async function checkReadiness() {
    const modes = [...document.querySelectorAll("[data-mode]:checked")].map((e) => e.dataset.mode);
    if (!modes.length) throw new Error("Select at least one test mode.");
    const inputs = [...document.querySelectorAll(".bot")].map((card) => cards.get(card) || {});
    const targets = [...document.querySelectorAll(".bot")].map((card) => ({
      url: card.querySelector('[data-field="url"]')?.value.trim() || "",
      archive_id: card.dataset.archive || "",
    }));
    $("readiness-results").textContent = "Checking files and scanner tools…";
    renderReadiness(await api("/api/assurance/preflight", { modes, inputs, targets }));
  }
  function clearReadiness() {
    if ($("readiness-results").textContent)
      $("readiness-results").textContent = "Inputs changed. Check readiness again.";
  }
  function syncInputs() {
    document.querySelectorAll("[data-evidence-mode]").forEach((element) => {
      element.hidden = !document.querySelector(`[data-mode="${element.dataset.evidenceMode}"]`)
        .checked;
    });
  }
  const active = (run) => ["running", "queued"].includes(run?.status);
  function select(value) {
    id = value || null;
    const url = new URL(location.href);
    if (id) url.searchParams.set("assessment", id);
    else url.searchParams.delete("assessment");
    window.history.replaceState(null, "", url);
    if (id) {
      window.StudioUI.selectAssessment(id, { notify: false, replace: true });
      window.dispatchEvent(new CustomEvent("studio:run-selected", { detail: { id: null } }));
    }
  }
  function addInputs() {
    for (const card of document.querySelectorAll(".bot")) {
      if (cards.has(card)) continue;
      cards.set(card, {});
      card.insertAdjacentHTML(
        "beforeend",
        `<div data-evidence-mode="white" class="source-inputs" hidden>
          <label>Source code ZIP<input type="file" data-private="code" accept=".zip"></label>
          <small data-ready="code"></small>
          <details><summary>Use a public GitHub repository instead</summary>
            <label>Repository link<input data-repository placeholder="https://github.com/owner/repo/tree/main"></label>
            <button type="button" data-source>Import source</button>
          </details>
        </div>
        <div data-evidence-mode="gray" class="source-inputs" hidden>
          <p class="helper">Add the files you want reviewed. A local judge is used unless you allow cloud access in Advanced settings.</p>
          <div class="grid">${Object.entries(kinds)
            .filter(([kind]) => kind !== "code")
            .map(
              ([kind, label]) =>
                `<div><label>${esc(label)}<input type="file" data-private="${kind}"></label><small data-ready="${kind}"></small></div>`,
            )
            .join("")}</div>
          <details><summary>Update logs for a previous test</summary><button type="button" data-canary>Attach updated test logs</button></details>
        </div>`,
      );
      card.querySelectorAll("[data-private]").forEach(
        (input) =>
          (input.onchange = async () => {
            try {
              if (!input.files.length) return;
              const body = new FormData();
              body.append("file", input.files[0]);
              const response = await fetch(`/api/assurance/inputs/${input.dataset.private}`, {
                method: "POST",
                headers: { "X-Studio-Request": "1" },
                body,
              });
              const result = await response.json();
              if (!response.ok)
                throw new Error(
                  typeof result.detail === "string" ? result.detail : "Upload failed",
                );
              cards.get(card)[input.dataset.private] = result.id;
              clearReadiness();
              card.querySelector(`[data-ready=${input.dataset.private}]`).textContent =
                `File ready · ${result.unlocks} checks available`;
            } catch (error) {
              tell(error.message);
            }
          }),
      );
      card.querySelector("[data-source]").onclick = async () => {
        try {
          const result = await api("/api/assurance/repository", {
            url: card.querySelector("[data-repository]").value.trim(),
            ownership_confirmed: $("ownership").checked,
          });
          cards.get(card).code = result.id;
          clearReadiness();
          card.querySelector("[data-ready=code]").textContent =
            `${result.unlocks} source checks have their input.`;
        } catch (error) {
          tell(error.message);
        }
      };
      card.querySelector("[data-canary]").onclick = async () => {
        try {
          if (!id || !cards.get(card).logs)
            throw new Error("Select the saved assessment and upload its new logs first.");
          await api(`/api/assurance/runs/${id}/canary-logs`, {
            bot: [...document.querySelectorAll(".bot")].indexOf(card),
            logs: cards.get(card).logs,
          });
          await refresh();
        } catch (error) {
          tell(error.message);
        }
      };
    }
    syncInputs();
  }
  function request() {
    const modes = [...document.querySelectorAll("[data-mode]:checked")].map((e) => e.dataset.mode);
    if (!modes.length) throw new Error("Select at least one test mode.");
    const cfg = configuration(),
      inputs = [...document.querySelectorAll(".bot")].map((card) => cards.get(card) || {});
    cfg.targets.forEach((target, index) => {
      if (!target.url && inputs[index].code) {
        target.kind = "zip";
        target.archive_id = inputs[index].code;
      }
    });
    return {
      settings: cfg,
      modes,
      inputs,
      ownership_confirmed: $("ownership").checked,
      private_cloud_opt_in: $("private-cloud").checked,
      upload_retention_days: Number($("upload-retention").value),
    };
  }
  function show(next) {
    tab = current && next !== "combined" && !current.modes.includes(next) ? "combined" : next;
    root
      .querySelectorAll("[data-assurance-tab]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.assuranceTab === tab)));
    [...$("results").children].forEach((e) => {
      if (e !== root && e.id !== "results-empty" && !e.classList.contains("page-heading"))
        e.hidden = !runId || tab !== "black";
    });
    $("results-empty").hidden = !!id || !!runId;
    root.hidden = !id;
    $("assurance-content").hidden = tab === "black";
    if (current && tab !== "black") render();
  }
  function render() {
    const run = current,
      c = run.combined,
      costs = run.assurance_costs;
    const explanations = run.ai_explanations || [];
    const accepted = [...explanations].reverse().find((item) => item.status === "accepted");
    const aiReview =
      run.ai_source_review ||
      (accepted && {
        ...accepted,
        model: `${accepted.source} by ${accepted.model}`,
        automation_status: accepted.attempts.map((a) => `${a.model}: ${a.status}`).join("; "),
      });
    const lastExplanation = explanations[explanations.length - 1];
    const explainPanel =
      run.modes.includes("white") && !active(run) && tab !== "gray"
        ? `<details class="explain-panel"><summary>Ask an AI judge to explain the White-box results</summary>
          <p class="helper">The explanation is added beside the results. It never changes a result. Local judges are used unless you allow a cloud judge below.</p>
          <label><input type="checkbox" id="explain-cloud"> Allow the selected cloud judge to read redacted source excerpts for this explanation only.</label>
          <button type="button" id="explain-run">Explain results</button>
          ${lastExplanation ? `<p class="helper">Last attempt: ${esc(lastExplanation.status === "accepted" ? `accepted from ${lastExplanation.model}` : lastExplanation.reason || "not accepted")}</p><ul>${lastExplanation.attempts.map((a) => `<li>${esc(a.model)} · ${esc(a.status)}${a.reason ? ` · ${esc(a.reason)}` : ""}</li>`).join("")}</ul>` : ""}
        </details>`
        : "";
    const aiChecks = new Map((aiReview?.checks || []).map((item) => [item.test_id, item]));
    const headings = ["What we checked", "What we found", "Why it matters", "How to fix it"];
    const opened = new Set(
      [...root.querySelectorAll("details[open][data-finding]")].map((e) => e.dataset.finding),
    );
    const rows = run.findings
      .filter((f) => tab === "combined" || f.mode === tab)
      .sort(
        (a, b) =>
          ["Critical", "High", "Medium", "Low", "Pass"].indexOf(a.severity) -
          ["Critical", "High", "Medium", "Low", "Pass"].indexOf(b.severity),
      );
    const matrix = table(
      ["Bot", "Category", ...run.modes.map((m) => modeNames[m]), "Result", "Confidence"],
      c.categories.map((r) => [
        String(r.bot + 1),
        esc(friendly(r.category)),
        ...run.modes.map((m) => esc(r.cells[m])),
        `<span title="${esc(r.reason)}">${esc(r.label)}</span>`,
        r.confidence,
      ]),
    );
    const status = run.evidence_status;
    const guidance = new Map((status?.checks || []).map((row) => [row.key, row]));
    const shown = rows.map((f) => guidance.get(`${f.bot}:${f.mode}:${f.test_id}`)).filter(Boolean);
    const count = (verdict) => rows.filter((f) => f.verdict === verdict).length;
    const stat = (label, value) =>
      `<article><strong>${esc(value)}</strong><span>${esc(label)}</span></article>`;
    const outcomeCounts = {};
    shown.forEach(
      (row) => (outcomeCounts[row.outcome_label] = (outcomeCounts[row.outcome_label] || 0) + 1),
    );
    const notProcessed = ["not_attempted", "missing_input", "tool_unavailable", "unverified"];
    const sourceSummary = status
      ? `<p class="helper">${esc(status.notice)}</p><p class="helper">Breakdown: ${Object.entries(
          outcomeCounts,
        )
          .map(([label, value]) => `${esc(label)} ${value}`)
          .join(
            " · ",
          )}</p>${aiReview ? `<p class="helper">${esc(status.historical_note)}</p>` : ""}`
      : "";
    $("assurance-content").innerHTML = `
      <div class="verdict-card">${aiReview ? '<p class="helper">Original scanner summary — see the qualified AI source review below.</p>' : ""}<h3>${esc(c.verdict)}</h3><p>${esc(c.reason)}</p></div>
      <div class="result-stats">
        ${stat("checks recorded", `${c.integrity.accounted}/${c.integrity.planned}`)}
        ${stat("processed", shown.filter((row) => !notProcessed.includes(row.outcome)).length)}
        ${stat("measured", count("pass") + count("fail"))}
        ${stat("passed", count("pass"))}${stat("need attention", count("fail"))}
        ${stat("declarations only", count("exists"))}${stat("not verified", count("not_tested"))}
        ${stat("waiting for review", rows.filter((f) => f.review && !f.overridden).length)}
      </div>
      ${count("exists") ? `<p>${count("exists")} checks found a declaration in the supplied files; its behavior is not verified.</p>` : ""}
      ${sourceSummary}
      <p class="helper">${run.duration_seconds == null ? "Test in progress" : `${run.duration_seconds} seconds`} · ${esc(c.assurance_note)}</p>
      ${costs ? `<p><strong>Usage:</strong> Bot ${costs.bot.calls ? costMoney(costs.bot) : "$0 (no bot API calls)"} · AI review ${costMoney(costs.evaluation)}<br><small>Bot tokens: ${costs.bot.input_tokens + costs.bot.output_tokens} · Review tokens: ${costs.evaluation.input_tokens + costs.evaluation.output_tokens}. Missing usage or prices stay Unknown.${costs.evaluation.unknown_calls ? ` Known metered review cost: $${(costs.evaluation.known_cost_micro_usd / 1000000).toFixed(6)}; ${costs.evaluation.unknown_calls} call(s) have unknown billing.` : ""}</small></p>` : ""}
      ${aiReview ? `<article class="verdict-card" aria-label="AI source review"><h3>AI explanation${aiReview.model ? ` — ${esc(aiReview.model)}` : ""}</h3><p>${esc(aiReview.summary)}</p><p class="helper">Additional source review. Original scanner results are retained; this is not human approval or a live chatbot test.</p>${aiReview.automation_status ? `<details><summary>AI review status and source</summary><p>${esc(aiReview.automation_status)}</p></details>` : ""}${run.source_review_context?.source_observations?.length ? `<details><summary>Source issues to discuss with your teammate</summary>${run.source_review_context.source_observations.map((item) => `<h4>${esc(item.title)} · ${esc(item.severity)}</h4><p>${esc(item.reason)}</p><p><strong>Suggested fix:</strong> ${esc(item.fix)}</p><p class="helper">${item.evidence.map(esc).join(" · ")}</p>`).join("")}</details>` : ""}</article>` : ""}
      ${tab === "combined" ? `<details><summary>Compare all categories</summary>${matrix}</details>` : ""}
      <div class="finding-list"><h3>What needs attention?</h3>
        <p class="helper">Open a check to see the reason, evidence and suggested next step. Not tested means evidence is missing.</p>
        ${rows
          .map((f) => {
            const key = `${f.bot}:${f.mode}:${f.test_id}`;
            const name = run.config?.targets?.[f.bot]?.name || `Bot ${f.bot + 1}`;
            const ai = f.mode === "white" ? aiChecks.get(f.test_id) : null;
            const g = guidance.get(key);
            const label =
              g && ["not_tested", "exists"].includes(f.verdict)
                ? g.outcome_label
                : resultNames[f.verdict] || f.verdict;
            const texts = [f.checked, f.explanation, f.consequence, f.fix];
            const replaced = g && g.unresolved && f.fix === genericFix && g.owner_action;
            if (replaced) texts[3] = g.owner_action;
            const help = g
              ? `<div class="evidence-help"><p><strong>Result type:</strong> ${esc(g.outcome_label)} · ${esc(g.cause_label)}</p><p><strong>Why:</strong> ${esc(g.why)}</p>${g.source_scope ? `<p class="helper">What this check can see: ${esc(g.source_scope)}</p>` : ""}${g.required_evidence.length ? `<p><strong>Evidence needed:</strong></p><ul>${g.required_evidence.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}${g.next_test ? `<p><strong>Next test:</strong> ${esc(g.next_test)}</p>` : ""}${replaced ? `<p class="helper">Original suggestion: ${esc(f.fix)}</p>` : ""}</div>`
              : "";
            return `<details data-finding="${esc(key)}" ${opened.has(key) ? "open" : ""}>
            <summary>${esc(g?.title || friendly(f.test_id))} <span class="summary-meta">${esc(label)}${f.verdict === "fail" ? ` · ${esc(f.severity)}` : ""}${f.overridden ? " · Overridden" : ""}</span></summary>
            <p class="helper">${esc(name)} · ${modeNames[f.mode]} · ${esc(f.confidence)} confidence${f.overridden && f.original_finding ? ` · Original result: ${esc(resultNames[f.original_finding.verdict] || f.original_finding.verdict)}` : ""}</p>
            ${texts.map((text, i) => `<p><strong>${headings[i]}:</strong> ${esc(text)}</p>`).join("")}
            ${help}
            ${ai ? `<p><strong>AI explanation (${esc(aiReview.model)}):</strong> ${esc(ai.explanation)}</p><p><strong>AI review:</strong> ${esc(friendly(ai.assessment))}</p><p><strong>Suggested next step:</strong> ${esc(ai.fix)}</p>` : ""}
            ${f.evidence.length ? f.evidence.map((e) => `<p class="helper">${esc(e.file || e.source_id || e.kind)}${e.line ? ":" + e.line : ""}</p><blockquote>${esc(e.excerpt)}</blockquote>`).join("") : "<p>No supporting evidence was obtained.</p>"}
            ${f.tool ? `<p class="helper">Checked by ${esc(f.tool)} ${esc(f.tool_version)}</p>` : ""}
            ${f.review && !active(run) ? `<button type="button" data-review="${esc(key)}">Review this finding</button>` : ""}
          </details>`;
          })
          .join("")}
      </div>
      ${explainPanel}
      <p class="helper">${c.review_queue.length} findings need review. <a href="#governance" data-view="governance">View governance</a></p>`;
    const explainButton = root.querySelector("#explain-run");
    if (explainButton)
      explainButton.onclick = async () => {
        try {
          explainButton.disabled = true;
          tell("Asking the judge to explain the results…");
          const result = await api(`/api/assurance/runs/${id}/explain`, {
            judges: judges(),
            cloud_consent: root.querySelector("#explain-cloud").checked,
          });
          tell(
            result.status === "accepted"
              ? "Explanation added. Results are unchanged."
              : result.reason || "No explanation was accepted.",
          );
          await refresh();
        } catch (error) {
          tell(error.message);
        } finally {
          explainButton.disabled = false;
        }
      };
    root.querySelectorAll("[data-review]").forEach(
      (button) =>
        (button.onclick = async () => {
          const reason = prompt(
            "Write why this is a false positive, or why you accept the finding:",
          );
          if (!reason) return;
          const false_positive = confirm(
              "Mark as false positive? Cancel keeps its score and records the review.",
            ),
            [bot, mode, ...test] = button.dataset.review.split(":");
          try {
            await api(`/api/assurance/runs/${id}/review`, {
              bot: Number(bot),
              mode,
              test_id: test.join(":"),
              false_positive,
              reason,
            });
            await refresh();
          } catch (error) {
            tell(error.message);
          }
        }),
    );
  }
  async function refresh() {
    if (!id || (busy && requestId === id)) return;
    requestController?.abort();
    requestController = new AbortController();
    const requestGeneration = ++generation;
    const selected = id;
    requestId = selected;
    busy = true;
    try {
      const run = await api(`/api/assurance/runs/${selected}`, undefined, "GET", {
        signal: requestController.signal,
      });
      if (id !== selected || requestGeneration !== generation) return;
      resultCache.set(run.id, run);
      if (resultCache.size > 10) resultCache.delete(resultCache.keys().next().value);
      current = run;
      root.hidden = false;
      $("run-toolbar").hidden = true;
      $("assurance-stop").hidden = !active(run);
      $("assurance-resume").hidden =
        active(run) || !run.findings.some((f) => f.verdict === "not_tested");
      ["assurance-delete", "assurance-reproduce"].forEach((key) => ($(key).disabled = active(run)));
      root
        .querySelectorAll("[data-assurance-tab]")
        .forEach(
          (b) =>
            (b.disabled =
              b.dataset.assuranceTab !== "combined" && !run.modes.includes(b.dataset.assuranceTab)),
        );
      if (run.blackbox_run_id && runId !== run.blackbox_run_id) {
        runId = run.blackbox_run_id;
        window.StudioUI.selectRun(runId, { notify: false, replace: true });
        await poll();
      }
      if (id !== selected || requestGeneration !== generation) return;
      $("assurance-status").textContent = `Test ${run.id.slice(0, 8)} · ${run.status}`;
      if (active(run)) {
        $("apply-judges").disabled = false;
        $("apply-judges").hidden = false;
      }
      if (tab !== "black") render();
      window.dispatchEvent(new CustomEvent("assurance:updated"));
    } catch (error) {
      if (requestGeneration === generation && id === selected && error.status === 404) {
        resultCache.delete(selected);
        current = null;
        window.StudioUI.selectAssessment(null, { replace: true });
        tell("This test is no longer available. Choose another test or start a new one.");
        return;
      }
      if (requestGeneration === generation && id === selected && error.name !== "AbortError")
        tell(error.message);
    } finally {
      if (requestGeneration === generation) busy = false;
    }
  }
  async function historyList() {
    const runs = await api("/api/assurance/runs");
    window.StudioUI.setAssessments(runs);
    $("assurance-saved").innerHTML =
      '<option value="">Choose a test</option>' +
      runs
        .map(
          (r) =>
            `<option value="${esc(r.id)}" ${r.id === id ? "selected" : ""}>${esc(r.modes.map((m) => modeNames[m]).join(" + "))} · ${esc(r.status)} · ${r.id.slice(0, 8)}</option>`,
        )
        .join("");
  }
  $("start").addEventListener(
    "click",
    async (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        $("start").disabled = true;
        const run = await api("/api/assurance/runs", request());
        select(run.id);
        window.StudioUI.navigate("results");
        await refresh();
        show("combined");
        tell("Test started. You can follow progress here.");
        await historyList();
      } catch (error) {
        tell(error.message);
      } finally {
        $("start").disabled = false;
      }
    },
    true,
  );
  $("apply-judges").addEventListener(
    "click",
    async (event) => {
      if (!id) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        await api(
          `/api/assurance/runs/${id}/judges`,
          { judges: judges(), consent: $("consent").checked },
          "PUT",
        );
        tell("Future cases use updated judges; private cloud consent stays unchanged.");
      } catch (error) {
        tell(error.message);
      }
    },
    true,
  );
  $("assurance-stop").onclick = async () => {
    try {
      if (id) {
        await api(`/api/assurance/runs/${id}/stop`, {});
        await refresh();
      }
    } catch (error) {
      tell(error.message);
    }
  };
  $("assurance-resume").onclick = async () => {
    try {
      await api(`/api/assurance/runs/${id}/resume`, request());
      tell("Resuming saved evidence; re-upload deleted inputs if requested.");
      await refresh();
    } catch (error) {
      tell(error.message);
    }
  };
  $("assurance-reproduce").onclick = async () => {
    try {
      if (!current) return;
      const data = request(),
        draft = data.settings;
      data.settings = { ...current.config, judges: draft.judges };
      data.settings.targets = current.config.targets.map((t, i) => ({
        ...t,
        token: draft.targets[i]?.url === t.url ? draft.targets[i].token : null,
      }));
      const result = await api(`/api/assurance/runs/${id}/reproduce`, data);
      select(result.id);
      await refresh();
      await historyList();
    } catch (error) {
      tell(error.message);
    }
  };
  $("assurance-delete").onclick = async () => {
    if (
      !id ||
      !confirm(
        "Delete this assessment/private inputs? Linked Black history stays separately deletable.",
      )
    )
      return;
    try {
      await api(`/api/assurance/runs/${id}`, {}, "DELETE");
      resultCache.delete(id);
      select(null);
      current = null;
      root.hidden = true;
      show("black");
      window.dispatchEvent(new CustomEvent("assurance:updated"));
      await historyList();
    } catch (error) {
      tell(error.message);
    }
  };
  $("check-readiness").onclick = () => checkReadiness().catch((error) => tell(error.message));
  document
    .querySelectorAll("[data-mode]")
    .forEach((e) => e.addEventListener("change", clearReadiness));
  for (const format of ["json", "pdf", "teammate"])
    $("assurance-" + format).onclick = () => {
      if (id) location.href = `/api/assurance/runs/${id}/download?format=${format}`;
    };
  root
    .querySelectorAll("[data-assurance-tab]")
    .forEach((b) => (b.onclick = () => show(b.dataset.assuranceTab)));
  document.querySelectorAll("[data-mode]").forEach((e) => e.addEventListener("change", syncInputs));
  $("assurance-saved").onchange = async () => {
    select($("assurance-saved").value);
    await refresh();
    show("combined");
  };
  new MutationObserver(addInputs).observe($("bots"), { childList: true });
  addInputs();
  window.addEventListener("studio:run-selected", (event) => {
    if (!new URLSearchParams(location.search).has("assessment")) {
      select(null);
      current = null;
      root.hidden = true;
      show("black");
      window.dispatchEvent(new CustomEvent("assurance:updated"));
    }
  });
  window.addEventListener("studio:assessment-selected", async (event) => {
    id = event.detail.id || null;
    current = resultCache.get(id) || null;
    $("assurance-content").textContent = "";
    $("assurance-status").textContent = id ? "Loading selected test…" : "Choose a test above.";
    show(id ? "combined" : "black");
    window.dispatchEvent(new CustomEvent("assurance:updated"));
    if (id) await refresh();
  });
  window.addEventListener("studio:view", () => id && (!current || active(current)) && refresh());
  window.addEventListener("studio:history-refresh", () => {
    historyList().catch((error) => tell(error.message));
    if (id) refresh();
  });
  setInterval(() => active(current) && refresh(), 3000);
  window.AssuranceUI = {
    get current() {
      return current;
    },
    get id() {
      return id;
    },
    refresh,
  };
  historyList()
    .then(refresh)
    .then(() => show(id ? "combined" : "black"))
    .catch((error) => tell(error.message));
})();
