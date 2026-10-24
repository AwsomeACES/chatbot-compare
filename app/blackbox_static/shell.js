/* One application, three views. Navigation never submits a test or resets form input. */
(() => {
  const panels = [...document.querySelectorAll("[data-panel]")];
  const links = [...document.querySelectorAll("nav [data-view]")];
  const selector = document.getElementById("selected-run");
  const titles = {
    evaluate: "Evaluate",
    results: "Results",
    governance: "Governance",
  };
  let runs = [],
    assessments = [];
  let assessment = new URLSearchParams(location.search).get("assessment");
  const historyPicker = document.getElementById("test-history");
  const modeNames = {
    black: "Black-box testing",
    gray: "Gray-box testing",
    white: "White-box testing",
  };
  function renderHistory() {
    historyPicker.replaceChildren(new Option("Choose a previous test", ""));
    const linked = new Set(assessments.map((run) => run.blackbox_run_id).filter(Boolean));
    const choices = [
      ...assessments.map((run) => ({
        value: "assessment:" + run.id,
        /* Tolerate a record saved without its modes: one bad row must not empty the picker. */
        label: `${(run.modes || []).map((m) => modeNames[m] || m).join(" + ") || "Modes not recorded"} · ${run.status} · ${run.id.slice(0, 8)}`,
      })),
      ...runs
        .filter((run) => !linked.has(run.id))
        .map((run) => ({
          value: "run:" + run.id,
          label: `${run.targets?.map((b) => b.name).join(" vs ") || "Chat test"} · ${run.status} · ${run.id.slice(0, 8)}`,
        })),
    ];
    choices.forEach((choice) => historyPicker.add(new Option(choice.label, choice.value)));
    const value = assessment ? "assessment:" + assessment : selected ? "run:" + selected : "";
    if (value && !choices.some((choice) => choice.value === value))
      historyPicker.add(
        new Option("Selected test · " + (assessment || selected).slice(0, 8), value),
      );
    historyPicker.value = value;
  }
  let selected = new URLSearchParams(location.search).get("run");
  let view;
  const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }));
  function readView() {
    const hash = location.hash.slice(1);
    if (!hash)
      return selected || new URLSearchParams(location.search).has("assessment")
        ? "results"
        : "evaluate";
    if (["setup", "checks"].includes(hash)) return "evaluate";
    if (["scores", "costs", "case-results", "usage-section", "bias-panel"].includes(hash))
      return "results";
    return titles[hash] ? hash : view || (selected ? "results" : "evaluate");
  }
  function urlFor(next) {
    const url = new URL(location.href);
    if (selected) url.searchParams.set("run", selected);
    else url.searchParams.delete("run");
    url.hash = next;
    return url;
  }
  function selectRun(id, { notify = true, replace = false } = {}) {
    selected = id || null;
    selector.value = selected || "";
    document.getElementById("run-label").textContent = selected ? "Loading…" : "No run selected";
    const url = urlFor(view);
    if (notify) {
      assessment = null;
      url.searchParams.delete("assessment");
    }
    window.history[replace ? "replaceState" : "pushState"](null, "", url);
    if (notify) emit("studio:run-selected", { id: selected });
    show(view);
  }
  function selectAssessment(id, { notify = true, replace = false } = {}) {
    assessment = id || null;
    selected = null;
    selector.value = "";
    const url = urlFor(view);
    if (assessment) url.searchParams.set("assessment", assessment);
    else url.searchParams.delete("assessment");
    window.history[replace ? "replaceState" : "pushState"](null, "", url);
    if (notify) {
      emit("studio:run-selected", { id: null });
      emit("studio:assessment-selected", { id: assessment });
    }
    show(view);
  }
  function show(next, focus = false) {
    view = next;
    panels.forEach((panel) => (panel.hidden = panel.dataset.panel !== view));
    links.forEach((link) => {
      if (link.dataset.view === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${titles[view]} — AI Agent Studio`;
    const assessmentSelected = new URLSearchParams(location.search).has("assessment");
    document.getElementById("run-toolbar").hidden = assessmentSelected || !selected;
    document.getElementById("history-toolbar").hidden = view === "evaluate";
    renderHistory();
    emit("studio:view", { view, id: selected });
    if (focus) {
      document.querySelector(`[data-panel="${view}"] h1`).focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  }
  function navigate(next) {
    window.history.pushState(null, "", urlFor(next));
    show(next, true);
  }
  function restore() {
    const id = new URLSearchParams(location.search).get("run");
    if (id !== selected) {
      selected = id;
      selector.value = id || "";
      emit("studio:run-selected", { id });
    }
    const nextAssessment = new URLSearchParams(location.search).get("assessment");
    if (nextAssessment !== assessment) {
      assessment = nextAssessment;
      emit("studio:assessment-selected", { id: assessment });
    }
    show(readView());
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-view]");
    if (
      !link ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey ||
      event.button !== 0
    )
      return;
    event.preventDefault();
    navigate(link.dataset.view);
  });
  historyPicker.addEventListener("change", () => {
    const value = historyPicker.value;
    if (value.startsWith("assessment:")) selectAssessment(value.slice(11));
    else selectRun(value.startsWith("run:") ? value.slice(4) : null);
  });
  selector.addEventListener("change", () => selectRun(selector.value));
  document.getElementById("refresh-history").onclick = () => emit("studio:history-refresh", {});
  document.getElementById("refresh-run").onclick = () => emit("studio:refresh", { id: selected });
  window.history.scrollRestoration = "manual";
  window.addEventListener("load", () => {
    if (["", "#evaluate", "#results", "#governance", "#setup"].includes(location.hash)) {
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  });
  window.addEventListener("hashchange", restore);
  window.addEventListener("popstate", restore);
  window.StudioUI = {
    navigate,
    selectRun,
    selectAssessment,
    get view() {
      return view;
    },
    get runId() {
      return selected;
    },
    setAssessments(items) {
      assessments = items;
      assessment = new URLSearchParams(location.search).get("assessment");
      renderHistory();
    },
    setRuns(items) {
      runs = items;
      selector.replaceChildren(new Option("Choose a saved run", ""));
      items.forEach((run) => {
        const label = `${run.targets?.map((b) => b.name).join(" vs ") || "Evaluation"} · ${run.status} · ${run.id.slice(0, 8)}`;
        selector.add(new Option(label, run.id));
      });
      if (selected && !items.some((run) => run.id === selected))
        selector.add(new Option(`Run ${selected.slice(0, 8)}`, selected));
      selector.value = selected || "";
      show(view);
    },
    updateRun(run) {
      if (run.id !== selected) return;
      document.getElementById("run-label").textContent = run.status.replaceAll("_", " ");
    },
  };
  show(readView());
})();
