/* Cost is always shown with measurement basis and pinned price source. */
(() => {
  const by = (id) => document.getElementById(id),
    escape = (x) =>
      String(x ?? "").replace(
        /[&<>"']/g,
        (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
      );
  let saved = {},
    priceInfo = {};
  async function request(url, options = {}) {
    const r = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
    });
    const d = await r.json();
    if (!r.ok) throw Error(typeof d.detail === "string" ? d.detail : "Please check cost settings.");
    return d;
  }
  function amount(value, source) {
    return `<span title="${escape(source)}">${value === null || value === undefined ? "Unknown" : "$" + (value / 1000000).toFixed(6)}</span>`;
  }
  function label(total) {
    if (!total.calls) return '<span class="badge">No calls</span>';
    return total.estimated
      ? '<span class="badge not_tested">Estimated</span>'
      : total.token_sources?.includes("counted")
        ? '<span class="badge">Counted</span>'
        : '<span class="badge">Reported usage</span>';
  }
  function setTab(cost) {
    by("cost-panel").hidden = !cost;
    by("evaluation-panel").hidden = cost;
    by("cost-tab").setAttribute("aria-selected", String(cost));
    by("evaluation-tab").setAttribute("aria-selected", String(!cost));
  }
  if (by("cost-tab")) by("cost-tab").onclick = () => setTab(true);
  if (by("evaluation-tab")) by("evaluation-tab").onclick = () => setTab(false);
  window.renderCost = (run) => {
    const c = run.costs;
    const panel = by("cost-panel");
    if (!c?.available) {
      panel._costHtml = null;
      panel._costRun = run.id;
      panel.innerHTML =
        '<article class="card"><h2>Cost tracking unavailable for this run</h2><p>' +
        escape(
          c?.note || "This historical run has no usage ledger. Start a new run to record cost.",
        ) +
        "</p></article>";
      return;
    }
    const source = c.price_source + " | Snapshot " + c.snapshot_date,
      m = (v) => amount(v, source);
    function totalCard(title, t) {
      return `<article class="card"><h3>${title}</h3><div class="score">${m(t.cost_micro_usd)}</div>${label(t)}<p>${t.input_tokens.toLocaleString()} input / ${t.output_tokens.toLocaleString()} output tokens</p><p>${t.calls} calls; ${t.unknown_calls} unknown or pending</p>${t.local_calls ? `<p>${t.local_calls} local calls: zero API charges. Compute estimate included: ${m(t.local_compute_micro_usd)}.</p>` : ""}<p class="help">Token sources: ${escape(t.token_sources.join(", ") || "Not measured")}. Cached: ${t.cached_input_tokens}; reasoning: ${t.reasoning_tokens} (already included in token totals).</p>${t.unknown_calls ? `<p>Known subtotal: ${m(t.known_cost_micro_usd)}; total remains Unknown.</p>` : ""}<small>${escape(source)}</small></article>`;
    }
    function table(rows) {
      return `<div class="scroll"><table><thead><tr><th>Group</th><th>Calls</th><th>Tokens (in / out)</th><th>Bot cost</th><th>Evaluation cost</th><th>Basis</th></tr></thead><tbody>${rows.map((x) => `<tr><td>${escape(x.name)}</td><td>${x.calls}</td><td>${x.input_tokens} / ${x.output_tokens}</td><td>${m(x.bot.cost_micro_usd)}</td><td>${m(x.evaluation.cost_micro_usd)}</td><td>${label(x)}</td></tr>`).join("")}</tbody></table></div>`;
    }
    const html = `<p class="help">Price source: ${escape(source)}</p><div class="columns">${totalCard("Bot cost — target calls", c.bot)}${totalCard("Evaluation cost — judging and test generation", c.evaluation)}</div><article class="card"><h3>Cost summary</h3><p>${escape(c.summary)}</p><p>${escape(c.coverage_note)}</p>${c.inr_per_usd ? `<p>Manual INR/USD rate: ${escape(c.inr_per_usd)}. Bot: ${c.bot.cost_micro_usd === null ? "Unknown" : "INR " + ((c.bot.cost_micro_usd / 1e6) * Number(c.inr_per_usd)).toFixed(2)}; Evaluation: ${c.evaluation.cost_micro_usd === null ? "Unknown" : "INR " + ((c.evaluation.cost_micro_usd / 1e6) * Number(c.inr_per_usd)).toFixed(2)}.</p>` : ""}${c.unknown_models.length ? `<p>Missing price or billing evidence: ${escape(c.unknown_models.join(", "))}</p>` : ""}</article><article class="card"><h3>Bot unit economics</h3>${c.comparison_warning ? `<p class="cost-warning">${escape(c.comparison_warning)}</p>` : ""}<p>${c.cheapest_qualifying_slot ? "Lowest projected cost meeting score " + c.score_threshold + ": Bot " + c.cheapest_qualifying_slot : "No comparable qualifying cost winner yet."}</p><div class="scroll"><table><thead><tr><th>Bot</th><th>Target total</th><th>Per answer</th><th>Tokens / answer</th><th>Per conversation</th><th>Tokens / conversation</th><th>Per 1,000 conversations</th><th>Latency</th><th>Quality / dollar</th></tr></thead><tbody>${c.bots.map((b) => `<tr><td>${escape(b.name)} ${label(b)}</td><td>${m(b.cost_micro_usd)}</td><td>${m(b.cost_per_answer_micro_usd)}</td><td>${b.tokens_per_answer ?? "Not measured"}</td><td>${m(b.cost_per_conversation_micro_usd)}</td><td>${b.tokens_per_conversation ?? "Not measured"}</td><td>${m(b.projected_1000_micro_usd)}</td><td>${b.mean_latency_ms === null ? "Not measured" : (b.mean_latency_ms / 1000).toFixed(2) + " s"}</td><td>${b.quality_per_dollar === null ? "Unavailable" : b.quality_per_dollar.toFixed(2)}</td></tr>`).join("")}</tbody></table></div><p class="help">All target attempts contribute to unit cost; successful answers/conversations form the denominator. Local compute is estimated separately from zero local API charges.</p></article><article class="card"><h3>Five most expensive cases by known subtotal</h3>${table(c.top_cases)}<p>Retries: ${m(c.retries.cost_micro_usd)} (${c.retries.calls} calls). Failed/timeout calls: ${m(c.failed_calls.cost_micro_usd)} (${c.failed_calls.calls} calls). These overlap and are already included above.</p></article>${Object.entries(
      c.breakdowns,
    )
      .map(
        ([key, rows]) =>
          `<details data-cost-group="${escape(key)}"><summary>Breakdown by ${escape(key.replaceAll("_", " "))}</summary>${table(rows)}</details>`,
      )
      .join("")}`;
    if (panel._costRun !== run.id) {
      panel._costHtml = null;
      panel._costRun = run.id;
      panel.innerHTML = "";
    }
    if (panel._costHtml !== html) {
      const open = [...panel.querySelectorAll("details[open]")].map((x) => x.dataset.costGroup);
      const firstRender = panel._costHtml == null;
      panel.innerHTML = html;
      panel._costHtml = html;
      panel
        .querySelectorAll("details")
        .forEach(
          (x) =>
            (x.open =
              open.includes(x.dataset.costGroup) ||
              (firstRender && x.dataset.costGroup === "category")),
        );
    }
  };
  // The unified Results screen reuses the read-only report, without legacy setup controls.
  if (!by("cost-tab")) return;
  window.confirmCost = async (config) => {
    const e = await request("/api/cost/estimate", { method: "POST", body: JSON.stringify(config) });
    const source = e.price_source + " | " + e.snapshot_date;
    by("cost-preview-body").innerHTML =
      `<p><span class="badge not_tested">Estimated</span> Based on ${e.average_input_tokens} input and ${e.average_output_tokens} output tokens per call.</p>${e.bots.map((b, i) => `<p>Bot ${"ABCD"[i]}: ${amount(b.cost_micro_usd, source)} (${b.calls} messages)</p>`).join("")}<p>Evaluation: ${amount(e.evaluation.cost_micro_usd, source)} (${e.evaluation.calls} judge requests)</p><p>${(e.warnings || []).map(escape).join("<br>")}</p><p>Run budget: ${e.budget_usd === null ? "Not set" : "USD " + escape(e.budget_usd)}</p><p>${escape(e.note)}</p><small>${escape(source)}</small>`;
    const dialog = by("cost-preview");
    dialog.showModal();
    return new Promise((resolve) => {
      const finish = (ok) => {
        dialog.close();
        resolve(ok);
      };
      by("cost-preview-go").onclick = () => finish(true);
      by("cost-preview-cancel").onclick = () => finish(false);
      dialog.oncancel = () => resolve(false);
    });
  };
  async function load() {
    const d = await request("/api/cost/settings");
    saved = d.settings;
    priceInfo = d.snapshot;
    by("cost-price-source").textContent =
      priceInfo.source + " | Snapshot " + priceInfo.date + " | " + d.model_count + " models";
    for (const [id, key] of [
      ["cost-budget", "max_budget_usd"],
      ["cost-compute", "compute_usd_hour"],
      ["cost-inr", "inr_per_usd"],
      ["cost-threshold", "quality_threshold"],
      ["cost-average-input", "average_input_tokens"],
      ["cost-average-output", "average_output_tokens"],
    ])
      by(id).value = saved[key] ?? "";
    for (let i = 0; i < 4; i++) {
      const name = by("name-" + i)?.value;
      if (name && saved.aliases?.[name]) by("cost-model-" + i).value = saved.aliases[name];
    }
  }
  by("save-cost-settings").onclick = async () => {
    try {
      const overrides = structuredClone(saved.overrides || {}),
        model = by("price-model").value.trim();
      if (model) {
        const rates = {};
        for (const key of [
          "input",
          "cached_input",
          "output",
          "reasoning",
          "cache_write",
          "cache_write_1h",
        ])
          if (by("price-" + key).value !== "") rates[key] = by("price-" + key).value;
        overrides[model] = rates;
      }
      const aliases = structuredClone(saved.aliases || {});
      for (let i = 0; i < 4; i++) {
        const name = by("name-" + i)?.value,
          alias = by("cost-model-" + i).value.trim();
        if (name) {
          if (alias) aliases[name] = alias;
          else delete aliases[name];
        }
      }
      saved = await request("/api/cost/settings", {
        method: "PUT",
        body: JSON.stringify({
          overrides,
          aliases,
          compute_usd_hour: by("cost-compute").value || "0",
          inr_per_usd: by("cost-inr").value || null,
          max_budget_usd: by("cost-budget").value || null,
          quality_threshold: Number(by("cost-threshold").value),
          average_input_tokens: Number(by("cost-average-input").value),
          average_output_tokens: Number(by("cost-average-output").value),
        }),
      });
      by("cost-settings-message").textContent =
        "Saved. New runs use these settings; older runs keep their original price snapshot.";
    } catch (e) {
      by("cost-settings-message").textContent = e.message;
    }
  };
  by("update-prices").onclick = async () => {
    by("update-prices").disabled = true;
    try {
      await request("/api/cost/prices/update", { method: "POST" });
      await load();
      by("cost-settings-message").textContent =
        "Price snapshot updated. Existing runs are unchanged.";
    } catch (e) {
      by("cost-settings-message").textContent = e.message;
    } finally {
      by("update-prices").disabled = false;
    }
  };
  load().catch((e) => (by("cost-settings-message").textContent = e.message));
})();
