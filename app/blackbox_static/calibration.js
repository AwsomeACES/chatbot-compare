/* Judge calibration: select saved conversations, label them independently, compare a Judge. */
/* Diagnostic only. Nothing here changes a score, verdict, winner or model-to-model agreement. */
(() => {
  const BASE = "/api/studio/judge-calibration";
  const byId = (id) => document.getElementById(id);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  const TITLES = {
    uncalibrated: "Not calibrated",
    stale: "Calibration out of date",
    incomplete: "Calibration incomplete",
    insufficient_sample: "Sample too small or unbalanced",
    not_aligned: "Not aligned with human labels",
    meets: "Meets configured calibration criteria",
  };
  const percent = (rate) => (rate && rate.percent != null ? `${rate.percent}%` : "Unavailable");
  const fraction = (rate) => (rate ? `${rate.numerator}/${rate.denominator}` : "0/0");

  async function call(url, method = "GET", body) {
    const response = await fetch(BASE + url, {
      method,
      headers: { "Content-Type": "application/json", "X-Studio-Request": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(
        typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`,
      );
      error.status = response.status;
      throw error;
    }
    return data;
  }

  /* ---- pure renderers (escape every dynamic value) ---- */
  function renderAlignment(summary, heading = "Human alignment") {
    if (!summary)
      return `<section class="alignment alignment-unavailable" role="status"><strong>${esc(heading)}: status unavailable.</strong><p>Judge calibration status could not be loaded. Treat the Judge as unverified against human labels.</p></section>`;
    const state = summary.state || "uncalibrated";
    const metrics =
      summary.comparable != null && state !== "uncalibrated"
        ? `<p class="helper">${esc(
            summary.agreement_percent == null
              ? "Agreement unavailable (no comparable items)."
              : `Agreement ${summary.agreement_percent}% (${summary.matching}/${summary.comparable} judged items matched the human label)`,
          )}${summary.coverage_percent != null ? ` · coverage ${esc(summary.coverage_percent)}%` : ""}</p>`
        : "";
    const reasons = (summary.stale_reasons || []).length
      ? `<ul>${summary.stale_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
      : "";
    return `<section class="alignment alignment-${esc(state)}" role="status" data-state="${esc(state)}"><strong>${esc(heading)}: ${esc(TITLES[state] || state)}</strong>${(summary.warnings || []).map((w) => `<p class="alignment-warning">${esc(w)}</p>`).join("")}${reasons}${metrics}<p class="helper">${esc(summary.conditional_note || "Conditional on a labeled sample and rubric; this is not certification.")} This is separate from model-to-model Judge agreement.${summary.judge_model ? ` Judge: ${esc(summary.judge_model)}.` : ""}</p></section>`;
  }

  function renderTranscript(transcript) {
    return (transcript || [])
      .map(
        (turn, index) =>
          `<div class="cal-turn"><small>Turn ${index + 1}</small><p><strong>User</strong></p><pre>${esc(turn.input)}</pre><p><strong>Bot</strong></p><pre>${esc(turn.output)}</pre></div>`,
      )
      .join("");
  }

  function renderDisagreements(rows) {
    if (!rows || !rows.length)
      return `<p class="helper">No disagreements among judged items. This is conditional on this sample.</p>`;
    return `<h4>Disagreements (${rows.length})</h4>${rows
      .map(
        (row) =>
          `<details class="cal-disagreement" open><summary>${esc(row.source.case_id)} · bot ${esc(row.source.bot_slot + 1)} · human ${esc(row.human.verdict)}${row.human.score == null ? "" : ` (${esc(row.human.score)})`} vs Judge ${esc(row.judge.verdict)} (${esc(row.judge.score)})</summary><dl><dt>Category</dt><dd>${esc(row.category)}</dd><dt>Expected criterion</dt><dd>${esc(row.criterion)}</dd><dt>Judge reason</dt><dd>${esc(row.judge.reason)}</dd><dt>Judge supporting excerpts</dt><dd>${(row.judge.evidence || []).map((q) => `<blockquote>${esc(q)}</blockquote>`).join("") || "None"}</dd><dt>Human rationale</dt><dd>${esc(row.human.rationale || "None given")}</dd><dt>Judge used</dt><dd>${esc(row.judge.actual_evaluator.requested_model)}${row.judge.fallback_used ? " (fallback; not the requested Judge)" : ""}</dd></dl><details><summary>Full retained conversation</summary>${renderTranscript(row.transcript)}</details></details>`,
      )
      .join("")}`;
  }

  function renderSummary(view) {
    const s = view.summary;
    if (!s)
      return `<p class="notice">${esc(view.note || "No summary available for this evaluation.")}</p>`;
    const c = s.counts;
    const matrix = s.confusion;
    const checks = s.sufficiency.checks
      .map(
        (k) =>
          `<tr><td>${esc(k.name.replaceAll("_", " "))}</td><td>${esc(k.actual ?? "n/a")}</td><td>${esc(k.required)}</td><td>${k.met ? "Met" : "Not met"}</td></tr>`,
      )
      .join("");
    const categories = Object.entries(s.sufficiency.categories)
      .map(
        ([name, v]) =>
          `<tr><td>${esc(name)}</td><td>${esc(v.labeled)}</td><td>${esc(v.comparable)}</td><td>${esc(v.scenarios)}</td></tr>`,
      )
      .join("");
    const fallback = view.partial_fallback
      ? `<p class="notice">Some items were judged by a fallback model. Fallback results are reported separately and never count as a completed evaluation of the requested Judge.</p>`
      : "";
    const others = Object.values(view.by_evaluator || {})
      .filter((e) => !e.requested)
      .map(
        (e) =>
          `<p class="helper">Fallback ${esc(e.evaluator.requested_model)}: ${esc(e.counts.validly_judged)} item(s) judged, agreement ${esc(percent(e.agreement))} (${esc(TITLES[e.state])}).</p>`,
      )
      .join("");
    const folds = Object.entries(view.by_fold || {})
      .map(
        ([name, f]) =>
          `<tr><td>${esc(name)}</td><td>${esc(f.counts.validly_judged)}</td><td>${esc(percent(f.agreement))} (${esc(fraction(f.agreement))})</td><td>${esc(f.sufficiency.distinct_scenarios)}</td><td>${esc(TITLES[f.state] || f.state)}</td></tr>`,
      )
      .join("");
    const foldTable = folds
      ? `<details><summary>Development and held-out folds</summary><table class="cal-table"><thead><tr><th>Fold</th><th>Judged</th><th>Agreement</th><th>Scenarios</th><th>State</th></tr></thead><tbody>${folds}</tbody></table><p class="helper">${esc(view.folds?.note || "")} Each fold has its own denominators. A fold is smaller than the whole sample, so read it as descriptive, not as a stronger result.</p></details>`
      : "";
    const cost = view.costs || {};
    return `${renderAlignment({ ...s, agreement_percent: s.agreement.percent, matching: s.counts.matching, comparable: s.counts.validly_judged, coverage_percent: s.coverage_percent, judge_model: view.judge.model, conditional_note: "Conditional on this sample and rubric; not certification, universal accuracy or an industry standard." }, "Human alignment for this evaluation")}${fallback}<table class="cal-table"><caption>Counts</caption><tbody><tr><th scope="row">Total selected</th><td>${c.total_selected}</td></tr><tr><th scope="row">Labeled</th><td>${c.labeled}</td></tr><tr><th scope="row">Attempted</th><td>${c.attempted}</td></tr><tr><th scope="row">Validly judged</th><td>${c.validly_judged}</td></tr><tr><th scope="row">Matching</th><td>${c.matching}</td></tr><tr><th scope="row">Disagreeing</th><td>${c.disagreeing}</td></tr><tr><th scope="row">Not tested</th><td>${c.not_tested}</td></tr><tr><th scope="row">Agreement (threshold ${esc(s.threshold)})</th><td>${esc(percent(s.agreement))} (${esc(fraction(s.agreement))})</td></tr></tbody></table><table class="cal-table"><caption>Confusion matrix</caption><thead><tr><th></th><th scope="col">Judge pass</th><th scope="col">Judge fail</th></tr></thead><tbody><tr><th scope="row">Human pass</th><td>${matrix.human_pass_judge_pass}</td><td>${matrix.human_pass_judge_fail}</td></tr><tr><th scope="row">Human fail</th><td>${matrix.human_fail_judge_pass}</td><td>${matrix.human_fail_judge_fail}</td></tr></tbody></table><p>False acceptance (human fail, Judge pass): ${esc(percent(s.false_acceptance))} (${esc(fraction(s.false_acceptance))}). False rejection (human pass, Judge fail): ${esc(percent(s.false_rejection))} (${esc(fraction(s.false_rejection))}).</p><details><summary>Sample sufficiency and coverage</summary><table class="cal-table"><thead><tr><th>Check</th><th>Actual</th><th>Required</th><th>Status</th></tr></thead><tbody>${checks}</tbody></table><p>${esc(s.sufficiency.repeated_scenarios)} scenario(s) have repeats; ${esc(s.sufficiency.duplicate_transcripts)} duplicate transcript(s). Repeats do not count as distinct scenarios.</p><table class="cal-table"><thead><tr><th>Category</th><th>Labeled</th><th>Judged</th><th>Scenarios</th></tr></thead><tbody>${categories}</tbody></table></details>${foldTable}${others}<p class="helper">Judge calls: ${esc(cost.calls ?? 0)} · cost ${esc(cost.status === "Unknown" ? "Unknown" : cost.cost_micro_usd == null ? "Unknown" : `$${(cost.cost_micro_usd / 1e6).toFixed(4)}`)} (calibration only; original Run cost unchanged). Returned model: ${esc(Object.values(view.results || {}).find((r) => r.actual)?.returned_model || "Not supplied")} (not a guaranteed immutable revision).</p>${renderDisagreements(view.disagreements)}<details><summary>Limitations</summary><ul>${(view.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>`;
  }

  /* ---- live status banner (Evaluate + Results): follows the selected Judge ---- */
  function selectedJudge() {
    const row = [...document.querySelectorAll(".judge")].find(
      (e) =>
        e.querySelector("[data-enabled]")?.checked && !e.querySelector("[data-fallback]")?.checked,
    );
    if (!row) return null;
    return {
      model: row.querySelector("[data-model]").value.trim(),
      url: row.dataset.url,
      local: row.dataset.local === "true",
      token: row.querySelector("[data-key]")?.value || null,
    };
  }
  let statusGeneration = 0;
  let statusTimer;
  async function refreshStatus() {
    const target = byId("calibration-status");
    if (!target) return;
    const generation = ++statusGeneration;
    const judge = selectedJudge();
    const html = (summary) =>
      [byId("calibration-status"), byId("calibration-banner-results")]
        .filter(Boolean)
        .forEach((e) => (e.innerHTML = renderAlignment(summary, "Selected Judge")));
    if (!judge || !judge.model) {
      html({
        state: "uncalibrated",
        warnings: [
          "Judge not calibrated against human labels. Agreement with human judgment is unverified.",
        ],
      });
      return;
    }
    try {
      const summary = await call("/compatibility", "POST", {
        model: judge.model,
        url: judge.url || "",
        policy: byId("policy")?.value || null,
        scope: byId("scope")?.value || null,
      });
      if (generation !== statusGeneration) return; // a newer Judge selection won the race
      html({ ...summary, judge_model: judge.model });
    } catch {
      if (generation === statusGeneration) html(null);
    }
  }
  function scheduleStatus() {
    clearTimeout(statusTimer);
    // Show the unverified state immediately so a model change never leaves a stale green status.
    const target = byId("calibration-status");
    if (target)
      target.innerHTML =
        '<section class="alignment alignment-pending" role="status"><strong>Selected Judge: checking calibration…</strong><p>Treat the Judge as unverified until this finishes.</p></section>';
    statusTimer = setTimeout(refreshStatus, 250);
  }

  /* ---- calibration workspace (Results view) ---- */
  const state = { generation: 0, source: null, set: null, evaluation: null, poll: null };
  const body = () => byId("calibration-body");
  const say = (text) => {
    const live = byId("calibration-message");
    if (live) live.textContent = text;
  };

  function currentSource() {
    const assessment = window.AssuranceUI?.current;
    if (assessment?.id) return { kind: "assurance_assessment", id: assessment.id };
    const id = window.StudioUI?.runId;
    return id ? { kind: "blackbox_run", id } : null;
  }

  function resetWorkspace() {
    state.generation++;
    clearTimeout(state.poll);
    state.set = state.evaluation = state.source = null;
    if (body())
      body().innerHTML =
        '<p class="helper">Choose a saved test, then open this panel to pick conversations for human labeling.</p>';
  }

  async function open() {
    const generation = ++state.generation;
    const source = currentSource();
    if (!body()) return;
    try {
      const sets = await call("/sets");
      if (generation !== state.generation) return;
      let listing = null;
      if (source)
        listing = await call(
          `/sources/${source.kind}/${encodeURIComponent(source.id)}/items`,
        ).catch((error) => ({ error: error.message }));
      if (generation !== state.generation) return;
      state.source = source;
      renderHome(sets, listing);
    } catch (error) {
      body().innerHTML = `<p class="notice">${esc(error.message)}</p>`;
    }
  }

  function renderHome(sets, listing) {
    const setOptions = sets
      .map(
        (s) =>
          `<option value="${esc(s.id)}">${esc(s.name)} · ${s.labeled}/${s.items} labeled · ${s.versions.length} version(s)${s.invalidated ? " · source deleted" : ""}</option>`,
      )
      .join("");
    let source = '<p class="helper">Select a saved test in Results to add conversations.</p>';
    if (listing?.error) source = `<p class="notice">${esc(listing.error)}</p>`;
    else if (listing) {
      const rows = listing.eligible
        .map(
          (i, index) =>
            `<label class="check cal-pick"><input type="checkbox" data-pick="${index}"> ${esc(i.case_id)} · ${esc(i.bot_name || `bot ${i.bot_slot + 1}`)} · ${esc(i.category)}<br><small>${esc(i.preview)}</small></label>`,
        )
        .join("");
      const excluded = listing.excluded.length
        ? `<details><summary>${listing.excluded.length} excluded item(s) and why</summary><ul>${listing.excluded.map((e) => `<li>${esc(e.case_id)} (bot ${esc(e.bot_slot + 1)}): ${esc(e.reason)}</li>`).join("")}</ul></details>`
        : "";
      source = `<fieldset><legend>Saved conversations from this test (${listing.eligible.length} eligible)</legend><div class="cal-picks">${rows || "<p>No eligible conversations.</p>"}</div>${excluded}<p class="helper">${esc(listing.note)}</p><label>Set name<input id="cal-name" maxlength="120" value="Calibration set"></label><div class="actions"><button type="button" id="cal-create-picked">Create set from checked</button></div><div class="grid"><label>Seeded sample size<input id="cal-size" type="number" min="1" max="100" value="60"></label><label>Seed<input id="cal-seed" type="number" min="0" value="42"></label></div><label><input type="checkbox" id="cal-stratify" checked> Spread the sample across Categories</label><label><input type="checkbox" id="cal-balance"> Include saved failures as well as successes (changes the sampled failure rate, so false acceptance and false rejection become conditional on it)</label><p class="helper">Labeling stays blind either way: the original Judge score and reason are never copied into a set.</p><div class="actions"><button type="button" id="cal-create-sample">Create seeded sample</button></div></fieldset>`;
    }
    body().innerHTML = `<p id="calibration-message" class="helper" role="status" aria-live="polite"></p>${source}<fieldset><legend>Existing calibration sets</legend><label>Continue a set<select id="cal-sets"><option value="">Choose a set</option>${setOptions}</select></label><div class="actions"><button type="button" id="cal-open">Open set</button><button type="button" class="danger-quiet" id="cal-delete-set">Delete set and its evaluations</button></div></fieldset><div id="cal-workspace"></div>`;
    const create = async (selection) => {
      try {
        const result = await call("/sets", "POST", {
          name: byId("cal-name").value || "Calibration set",
          selection: { source: state.source, ...selection },
        });
        say(
          `Set created with ${result.set.items} item(s); ${result.excluded.length} excluded. Labels start blank.`,
        );
        await openSet(result.set.id);
      } catch (error) {
        say(error.message);
      }
    };
    byId("cal-create-picked")?.addEventListener("click", () => {
      const items = [...document.querySelectorAll("[data-pick]:checked")].map((box) => {
        const item = listing.eligible[Number(box.dataset.pick)];
        return { case_id: item.case_id, bot_slot: item.bot_slot };
      });
      if (!items.length) return say("Check at least one conversation.");
      create({ items });
    });
    byId("cal-create-sample")?.addEventListener("click", () =>
      create({
        sample: {
          size: Number(byId("cal-size").value),
          seed: Number(byId("cal-seed").value),
          stratify: byId("cal-stratify").checked ? "category" : "none",
          balance_outcomes: byId("cal-balance").checked,
        },
      }),
    );
    byId("cal-open").addEventListener("click", () => {
      if (byId("cal-sets").value) openSet(byId("cal-sets").value);
    });
    byId("cal-delete-set").addEventListener("click", async () => {
      const id = byId("cal-sets").value;
      if (!id || !confirm("Delete this set, its labels, evaluations and copied evidence?")) return;
      try {
        await call(`/sets/${id}`, "DELETE");
        say("Set deleted.");
        open();
      } catch (error) {
        say(error.message);
      }
    });
  }

  async function openSet(id) {
    const generation = ++state.generation;
    try {
      const set = await call(`/sets/${id}`);
      const evaluations = await call(`/evaluations?set_id=${id}`);
      if (generation !== state.generation) return;
      state.set = set;
      renderSet(set, evaluations);
    } catch (error) {
      say(error.message);
    }
  }

  function renderItem(item) {
    const label = item.label;
    const reason =
      item.label_revision > 0
        ? `<label>Reason for changing this label (required)<input data-reason minlength="10" maxlength="2000"></label>`
        : "";
    const saved = label
      ? `<p class="helper" data-saved>Revision ${esc(label.revision)} by ${esc(label.author)} at ${esc(label.at)}: ${esc(label.verdict)}${label.score == null ? "" : ` (score ${esc(label.score)})`}</p>`
      : '<p class="helper" data-saved>Not labeled yet.</p>';
    return `<article class="bot cal-item" data-item="${esc(item.id)}" data-revision="${item.label_revision}"><h4>${esc(item.source.case_id)} · ${esc(item.source.bot_name || `bot ${item.source.bot_slot + 1}`)} <span class="pill">${esc(item.category)}</span></h4><details><summary>Conversation and expected criterion</summary><p><strong>Expected:</strong> ${esc(item.payload.criterion)}</p>${renderTranscript(item.payload.transcript)}</details><fieldset><legend>Your independent judgment</legend><label><input type="radio" name="v-${esc(item.id)}" value="pass"${label?.verdict === "pass" ? " checked" : ""}> Pass</label> <label><input type="radio" name="v-${esc(item.id)}" value="fail"${label?.verdict === "fail" ? " checked" : ""}> Fail</label> <label>or score 0–100 (80+ passes)<input data-score type="number" min="0" max="100" step="any"${label?.score == null ? "" : ` value="${esc(label.score)}"`}></label></fieldset><label>Rationale (optional; never sent to the Judge)<textarea data-rationale maxlength="2000">${esc(label?.rationale || "")}</textarea></label>${reason}<div class="actions"><button type="button" data-save>Save label</button></div>${saved}</article>`;
  }

  function renderSet(set, evaluations) {
    const versions = set.versions
      .map(
        (v) =>
          `<option value="${v.version}">Version ${v.version} · ${v.items} items · ${esc(v.hash.slice(0, 12))}${v.purged ? " · evidence deleted" : ""}</option>`,
      )
      .join("");
    const judge = selectedJudge();
    const invalid = set.invalidated
      ? `<p class="notice">Source evidence for this set was deleted or expired. Copied evidence was removed and dependent calibration is invalid.</p>`
      : "";
    const done = evaluations
      .map(
        (e) =>
          `<option value="${esc(e.id)}">${esc(e.judge.model)} · v${e.set_version} · ${esc(e.status)}${e.invalidated ? " · invalidated" : ""}</option>`,
      )
      .join("");
    byId("cal-workspace").innerHTML =
      `<h3>${esc(set.name)}</h3>${invalid}<p class="helper">${esc(set.blinding.note)} Prior exposure may still have occurred.</p><p class="helper">${set.labeled}/${set.items} labeled. Edits create revisions; frozen versions never change.</p><div id="cal-items">${set.items_detail.map(renderItem).join("")}</div><div class="grid"><label>Hold out this percentage of scenarios<input id="cal-holdout" type="number" min="0" max="50" step="5" value="0"></label><label>Holdout seed<input id="cal-holdout-seed" type="number" min="0" value="42"></label></div><p class="helper">A held-out subset is split by scenario, so repeats stay together. Review disagreements in the development fold, then read the holdout fold after changing the Judge, prompt or rubric. 0 reserves nothing.</p><div class="actions"><button type="button" id="cal-freeze">Freeze a new version</button></div><fieldset><legend>Evaluate a Judge on a frozen version</legend><label>Version<select id="cal-version">${versions}</select></label><p class="helper">Judge: ${judge?.model ? `${esc(judge.model)} (${judge.local ? "local" : "cloud"}) at ${esc(judge.url)}` : "Choose a judge in Evaluate first."} The Judge sees only the saved conversation and rubric. No bot is called and human labels are never sent.</p>${judge && !judge.local ? `<label class="consent"><input type="checkbox" id="cal-consent"> Allow sending this frozen calibration payload to ${esc(judge.url)}</label>` : ""}<div class="actions"><button type="button" id="cal-start"${judge?.model && set.versions.length ? "" : " disabled"}>Start evaluation</button></div></fieldset><fieldset><legend>Previous calibration evaluations</legend><label>Evaluation<select id="cal-evals"><option value="">Choose one</option>${done}</select></label><div class="actions"><button type="button" id="cal-view">View results</button></div></fieldset><div id="cal-result" aria-live="polite"></div>`;
    wireSet(set);
  }

  function wireSet(set) {
    document.querySelectorAll(".cal-item").forEach((card) => {
      card.querySelector("[data-save]").addEventListener("click", async () => {
        const verdict = card.querySelector("input[type=radio]:checked")?.value;
        const scoreText = card.querySelector("[data-score]").value.trim();
        const payload = {
          expected_revision: Number(card.dataset.revision),
          rationale: card.querySelector("[data-rationale]").value,
          change_reason: card.querySelector("[data-reason]")?.value || "",
        };
        if (verdict) payload.verdict = verdict;
        if (scoreText !== "") payload.score = Number(scoreText);
        if (!verdict && scoreText === "") return say("Choose pass or fail, or enter a score.");
        try {
          const saved = await call(
            `/sets/${set.id}/items/${card.dataset.item}/label`,
            "PUT",
            payload,
          );
          card.dataset.revision = saved.label_revision;
          card.querySelector("[data-saved]").textContent =
            `Revision ${saved.label.revision} by ${saved.label.author} at ${saved.label.at}: ${saved.label.verdict}`;
          say("Label saved as a new revision.");
        } catch (error) {
          say(error.message);
          if (error.status === 409) openSet(set.id); // stale edit: reload the current revision
        }
      });
    });
    byId("cal-freeze").addEventListener("click", async () => {
      try {
        const fresh = await call(`/sets/${set.id}`);
        await call(`/sets/${set.id}/freeze`, "POST", {
          expected_set_revision: fresh.revision,
          holdout_percent: Number(byId("cal-holdout").value) || 0,
          holdout_seed: Number(byId("cal-holdout-seed").value) || 0,
        });
        say("Version frozen.");
        openSet(set.id);
      } catch (error) {
        say(error.message);
      }
    });
    byId("cal-start")?.addEventListener("click", async () => {
      const judge = selectedJudge();
      const version = Number(byId("cal-version").value);
      const frozen = set.versions.find((v) => v.version === version);
      if (!judge || !frozen) return say("Choose a Judge and a frozen version.");
      const consent = byId("cal-consent");
      if (!judge.local && !consent?.checked)
        return say("Cloud Judges need your explicit consent for this payload and destination.");
      try {
        const started = await call(`/sets/${set.id}/evaluations`, "POST", {
          version,
          judge: { model: judge.model, url: judge.url, token: judge.token, local: judge.local },
          cloud_consent: judge.local ? null : { endpoint: judge.url, content_hash: frozen.hash },
        });
        say("Evaluation started.");
        watch(started.id);
      } catch (error) {
        say(error.message);
      }
    });
    byId("cal-view").addEventListener("click", () => {
      if (byId("cal-evals").value) watch(byId("cal-evals").value);
    });
  }

  async function watch(id) {
    const generation = state.generation;
    clearTimeout(state.poll);
    try {
      const view = await call(`/evaluations/${id}`);
      if (generation !== state.generation) return;
      state.evaluation = view;
      const box = byId("cal-result");
      if (!box) return;
      const running = ["queued", "running"].includes(view.status);
      box.innerHTML = `<h3>Evaluation ${esc(view.id.slice(0, 8))} · ${esc(view.status)}</h3>${running ? `<progress max="${view.progress?.labeled || 1}" value="${view.progress?.done || 0}" aria-label="Evaluation progress"></progress>` : ""}<div class="actions">${running ? '<button type="button" id="cal-cancel">Cancel</button>' : ""}${["interrupted", "cancelled"].includes(view.status) && !view.invalidated ? '<button type="button" id="cal-resume">Resume pending items</button>' : ""}<a class="button" href="${BASE}/evaluations/${esc(view.id)}/export">Export redacted JSON</a><button type="button" class="danger-quiet" id="cal-delete-eval"${running ? " disabled" : ""}>Delete evaluation</button></div>${renderSummary(view)}`;
      byId("cal-cancel")?.addEventListener("click", () =>
        call(`/evaluations/${id}/cancel`, "POST", {}).then(
          () => watch(id),
          (e) => say(e.message),
        ),
      );
      byId("cal-resume")?.addEventListener("click", () =>
        call(`/evaluations/${id}/resume`, "POST", {}).then(
          () => watch(id),
          (e) => say(e.message),
        ),
      );
      byId("cal-delete-eval").addEventListener("click", async () => {
        if (!confirm("Delete this evaluation, its results and cached Judge output?")) return;
        try {
          await call(`/evaluations/${id}`, "DELETE");
          box.innerHTML = "";
          say("Evaluation deleted.");
        } catch (error) {
          say(error.message);
        }
      });
      if (running) state.poll = setTimeout(() => watch(id), 1500);
      else refreshStatus();
    } catch (error) {
      say(error.message);
    }
  }

  function boot() {
    const panel = byId("calibration-panel");
    if (panel) panel.addEventListener("toggle", () => panel.open && open());
    const judges = byId("judges");
    if (judges) {
      judges.addEventListener("input", scheduleStatus);
      judges.addEventListener("change", scheduleStatus);
      new MutationObserver(scheduleStatus).observe(judges, { childList: true });
    }
    ["policy", "scope"].forEach((id) => byId(id)?.addEventListener("change", scheduleStatus));
    window.addEventListener("studio:view", (event) => {
      if (event.detail.id !== state.source?.id && state.source) resetWorkspace();
      if (panel?.open) open();
    });
    window.addEventListener("assurance:updated", () => panel?.open && open());
    resetWorkspace();
    refreshStatus();
  }

  window.CalibrationUI = { renderAlignment, renderDisagreements, renderSummary, esc, TITLES };
  if (typeof document !== "undefined" && byId("main")) boot();
})();
