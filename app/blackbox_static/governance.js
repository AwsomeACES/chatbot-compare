/* Lazy governance view in the shared shell. Keys stay in password fields only. */
(() => {
  const el = (id) => document.getElementById(`gov-${id}`);
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  let selected;
  let storedJudges = [];
  let loaded;
  let generation = 0;
  let busy = false;
  let active = false;
  const controls = ["reproduce", "save-retention", "delete"];
  async function request(url, method = "GET", data) {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    const result = await response.json();
    if (!response.ok)
      throw Error(typeof result.detail === "string" ? result.detail : "Request failed");
    return result;
  }
  function reset() {
    generation++;
    loaded = null;
    storedJudges = [];
    [
      "integrity",
      "cards",
      "warnings",
      "metadata",
      "audit",
      "mapping",
      "credentials",
      "human",
    ].forEach((id) => (el(id).textContent = ""));
    controls.forEach((id) => (el(id).disabled = true));
    el("export").hidden = true;
    el("status").textContent = selected
      ? "Loading audit evidence…"
      : "Choose a saved evaluation to inspect its audit.";
  }
  async function load(force = false) {
    if (!selected || (loaded === selected && !force)) return;
    const id = selected;
    const token = ++generation;
    controls.forEach((key) => (el(key).disabled = true));
    el("status").textContent = "Loading audit evidence…";
    try {
      const [g, run] = await Promise.all([
        request(`/api/studio/runs/${id}/governance`),
        request(`/api/blackbox/runs/${id}`),
      ]);
      if (token !== generation || id !== selected) return;
      storedJudges = run.config.judges || [];
      const i = g.run_integrity;
      const chain = g.audit_integrity.valid;
      const metric = (label, value, note) =>
        `<article class="metric"><small>${escape(label)}</small><strong class="stat-value">${escape(value)}</strong><p>${escape(note)}</p></article>`;
      el("integrity").innerHTML =
        `<div class="grid integrity-grid">${metric("Accounted for", `${i.accounted_for}/${i.planned}`, `${i.scored} scored · ${i.not_tested} not tested · ${i.pending} pending`)}${metric("Audit chain", chain === null ? "Unavailable" : chain ? "Intact" : "Changed", g.audit_integrity.reason)}${metric("Judge agreement (model vs model)", i.agreement_percent == null ? "Not measured" : `${i.agreement_percent}%`, `${i.low_agreement_cases.length} items flagged for review`)}${metric("Human overrides", i.overrides, "Every override keeps the original score and a written reason.")}</div>`;
      el("human").innerHTML = (g.human_alignment || [])
        .map((entry) => window.CalibrationUI.renderAlignment(entry, entry.judge_model || "Judge"))
        .join("");
      if (!g.human_alignment?.length)
        el("human").innerHTML = window.CalibrationUI.renderAlignment(null);
      el("warnings").innerHTML =
        g.warnings.map((warning) => `<p class="notice">${escape(warning)}</p>`).join("") +
        (i.low_agreement_cases.length
          ? `<details><summary>Items needing human review</summary><p>${escape(i.low_agreement_cases.join(", "))}</p></details>`
          : "");
      el("cards").innerHTML = [
        ...g.bot_cards.map(
          (b) =>
            `<article class="metric"><span class="pill">Bot</span><h3>${escape(b.name)}</h3><p>${escape(b.declared_model)}</p><small>${escape(b.url)}<br>${escape(b.connection)}</small></article>`,
        ),
        ...g.judge_cards.map(
          (j) =>
            `<article class="metric"><span class="pill">${j.local ? "Local judge" : "Cloud judge"}${j.fallback ? " · fallback" : ""}</span><h3>${escape(j.model)}</h3><p>Revision: ${escape(j.revision)}</p><small>${escape(j.endpoint)}</small></article>`,
        ),
      ].join("");
      el("metadata").innerHTML =
        `<p><strong>Run ID</strong><br>${escape(id)}</p><p><strong>Test suite</strong><br>${escape(g.suite_version)}</p><p><strong>Config hash</strong><br>${escape(g.config_hash)}</p><p>${escape(g.reproduction_note)}</p>`;
      el("audit").textContent = JSON.stringify(run.audit || [], null, 2);
      el("mapping").innerHTML =
        `<p>${escape(g.mapping.disclaimer)}</p>` +
        Object.entries(g.mapping.categories)
          .map(
            ([category, mapping]) =>
              `<details><summary>${escape(category)}</summary><pre>${escape(JSON.stringify(mapping, null, 2))}</pre></details>`,
          )
          .join("");
      el("credentials").innerHTML =
        g.judge_cards
          .map((j, index) =>
            j.local
              ? ""
              : `<label>${escape(j.model)} API key (only if needed)<input type="password" autocomplete="off" data-judge-key="${index}"></label>`,
          )
          .join("") +
        g.bot_cards
          .map(
            (b, index) =>
              `<label>${escape(b.name)} token (only if originally required)<input type="password" autocomplete="off" data-bot-key="${index}"></label>`,
          )
          .join("");
      el("days").value = g.retention_days;
      el("export").href = `/api/blackbox/runs/${id}/download?format=json`;
      el("export").hidden = false;
      active = ["running", "queued"].includes(run.status);
      controls.forEach((key) => (el(key).disabled = busy || active));
      el("status").textContent = active
        ? "This evaluation is running. Refresh to update integrity. Repeat and data changes become available when it finishes."
        : "Evidence loaded. Review any missing tests or warnings before using the result.";
      loaded = id;
    } catch (error) {
      if (token === generation) el("status").textContent = error.message;
    }
  }
  function act(action) {
    return async () => {
      if (busy || !selected || loaded !== selected) return;
      busy = true;
      controls.forEach((id) => (el(id).disabled = true));
      try {
        await action(selected);
      } catch (error) {
        el("status").textContent = error.message;
      } finally {
        busy = false;
        if (loaded === selected) controls.forEach((id) => (el(id).disabled = active));
      }
    };
  }
  el("reproduce").onclick = act(async (id) => {
    const run = await request(`/api/studio/runs/${id}/reproduce`, "POST", {
      ownership_confirmed: document.getElementById("ownership")?.checked || false,
      judges: storedJudges.map((judge, index) => ({
        ...judge,
        token: el("credentials").querySelector(`[data-judge-key="${index}"]`)?.value || null,
      })),
      target_tokens: [...el("credentials").querySelectorAll("[data-bot-key]")].map(
        (input) => input.value || null,
      ),
    });
    location.href = `/?run=${encodeURIComponent(run.id)}#results`;
  });
  el("save-retention").onclick = act(async (id) => {
    const input = el("days");
    if (!input.reportValidity()) return;
    await request(`/api/studio/runs/${id}/retention`, "PUT", { days: Number(input.value) });
    await load(true);
    if (id === selected) el("status").textContent = "Data retention saved.";
  });
  el("delete").onclick = act(async (id) => {
    if (
      !confirm(
        "Delete this run, usage and cached evidence permanently? Downloaded copies are unchanged.",
      )
    )
      return;
    await request(`/api/blackbox/runs/${id}`, "DELETE");
    location.href = "/#governance";
  });
  window.addEventListener("studio:view", (event) => {
    if (event.detail.id !== selected) {
      selected = event.detail.id;
      reset();
    }
    if (event.detail.view === "governance") load();
  });
  window.addEventListener("studio:refresh", () => {
    if (window.StudioUI.view === "governance") load(true);
  });
  window.addEventListener("studio:run-rendered", (event) => {
    const signature = `${event.detail.id}:${event.detail.status}:${event.detail.overrides}`;
    if (el("integrity").dataset.signature !== signature) {
      el("integrity").dataset.signature = signature;
      loaded = null;
      if (window.StudioUI.view === "governance") load();
    }
  });
  selected = window.StudioUI.runId;
  reset();
  if (window.StudioUI.view === "governance") load();
})();
