/* Keep the shared Governance view on the selected multi-mode assessment. */
(() => {
  const view = document.getElementById("governance"),
    panel = document.createElement("section");
  panel.id = "assurance-governance";
  panel.hidden = true;
  view.append(panel);
  let humanToken = 0;
  async function humanAlignment(run) {
    const token = ++humanToken;
    const target = () => document.getElementById("assurance-human-body");
    const show = (entries) => {
      if (token !== humanToken || !target()) return;
      target().innerHTML = entries.length
        ? entries
            .map((entry) =>
              window.CalibrationUI.renderAlignment(entry, entry.judge_model || "Judge"),
            )
            .join("")
        : window.CalibrationUI.renderAlignment(null);
    };
    if (!run.blackbox_run_id)
      return show([
        {
          state: "uncalibrated",
          warnings: [
            "Judge not calibrated against human labels. Agreement with human judgment is unverified.",
          ],
          headline: "No recorded Black Run.",
        },
      ]);
    try {
      const governance = await api(`/api/studio/runs/${run.blackbox_run_id}/governance`);
      show(governance.human_alignment || []);
    } catch {
      show([]);
    }
  }
  function render() {
    const run = window.AssuranceUI?.current;
    [...view.children].forEach((element) => {
      if (!element.classList.contains("page-heading"))
        element.hidden = run ? element !== panel : element === panel;
    });
    if (!run) return;
    panel.innerHTML = `<h2>Assessment ${esc(run.id.slice(0, 8))}</h2><p>${esc(run.combined.assurance)} · ${esc(run.combined.verdict)} · Audit ${run.audit_integrity?.valid ? "Intact" : "Needs review"}</p><p>${esc(run.combined.assurance_note)}</p><p>${esc((run.model_cards?.warning || []).join(" "))}</p><section id="assurance-human"><h3>Human alignment</h3><p class="helper">Compared with labels you entered yourself; separate from model-to-model judge agreement.</p><div id="assurance-human-body">Loading human alignment status…</div></section><details><summary>Bots and AI judges</summary><pre>${esc(JSON.stringify(run.model_cards, null, 2))}</pre></details><p>${run.combined.review_queue.length} findings need review. Open Results / Summary for evidence and written overrides.</p><label>Keep uploaded files (days)<input id="assurance-keep-days" type="number" min="0" max="30" value="${run.upload_retention_days || 0}"></label><div class="actions"><button type="button" data-assurance-action="retention">Save retention</button><button type="button" data-assurance-action="reproduce">Repeat this test</button><button type="button" data-assurance-action="json">Download data</button><button type="button" data-assurance-action="pdf">Download report</button><button type="button" data-assurance-action="delete">Delete this test</button></div><details><summary>Input hashes, audit and informational mappings</summary><pre>${esc(JSON.stringify({ inputs: run.input_hashes, audit: run.audit, mapping: run.combined.mapping }, null, 2))}</pre></details>`;
    humanAlignment(run);
    panel.querySelectorAll("[data-assurance-action]").forEach(
      (button) =>
        (button.onclick = async () => {
          if (button.dataset.assuranceAction !== "retention") {
            document.getElementById("assurance-" + button.dataset.assuranceAction).click();
            return;
          }
          try {
            await api(
              `/api/assurance/runs/${run.id}/retention`,
              {
                days: Number(document.getElementById("assurance-keep-days").value),
              },
              "PUT",
            );
            await window.AssuranceUI.refresh();
            tell("Retention saved; deleted uploads cannot be restored.");
          } catch (error) {
            tell(error.message);
          }
        }),
    );
  }
  window.addEventListener("assurance:updated", render);
  window.addEventListener("studio:view", render);
})();
