/* Run with node --test scripts/test-studio-navigation.cjs. No browser or paid API calls. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const repo = process.env.STUDIO_REPO || path.resolve(__dirname, "..");
const source = readFileSync(path.join(repo, "app/blackbox_static/shell.js"), "utf8");

test("cost summary keeps known subtotals visible without inventing a complete bill", () => {
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  const context = vm.createContext({
    window: { StudioStatus: { QUALIFIER: { unknown: "Unknown" } } },
  });
  vm.runInContext(
    simple.slice(simple.indexOf("const money ="), simple.indexOf("function table(")),
    context,
  );
  const format = (row) => vm.runInContext(`costMoney(${JSON.stringify(row)})`, context);
  assert.match(
    format({ cost_micro_usd: null, known_cost_micro_usd: 131359 }),
    /\$0\.131359 known subtotal/,
  );
  assert.match(format({ cost_micro_usd: null, known_cost_micro_usd: 131359 }), /Total unknown/);
  assert.equal(format({ cost_micro_usd: null }), "Unknown");
  assert.equal(format({ cost_micro_usd: 63179 }), "$0.063179");
  assert.equal(format({ cost_micro_usd: 0, calls: 1, local_calls: 1 }), "$0 (local)");
  assert.match(format({ cost_micro_usd: null, known_cost_micro_usd: 0 }), /Total unknown/);
});

function element(dataset = {}) {
  const listeners = new Map();
  return {
    dataset,
    hidden: false,
    value: "",
    textContent: "",
    attributes: new Map(),
    children: [],
    addEventListener(name, callback) {
      listeners.set(name, callback);
    },
    trigger(name) {
      listeners.get(name)?.({ target: this });
    },
    setAttribute(name, value) {
      this.attributes.set(name, value);
    },
    removeAttribute(name) {
      this.attributes.delete(name);
    },
    replaceChildren(...children) {
      this.children = children;
    },
    add(child) {
      this.children.push(child);
    },
    focus() {
      this.focused = true;
    },
  };
}

function application(initialUrl = "http://localhost:2708/") {
  const names = ["evaluate", "results", "governance"];
  const panels = names.map((name) => element({ panel: name }));
  const links = names.map((name) => element({ view: name }));
  const headings = Object.fromEntries(names.map((name) => [name, element()]));
  const fields = {
    "selected-run": element(),
    "test-history": element(),
    "history-toolbar": element(),
    "refresh-history": element(),
    "run-toolbar": element(),
    "refresh-run": element(),
    "run-label": element(),
    "bot-url": { value: "https://my-bot.example/chat" },
    "judge-key": { value: "synthetic-test-key" },
    "judge-selected": { checked: true },
  };
  const documentListeners = new Map();
  const windowListeners = new Map();
  const events = [];
  let address = new URL(initialUrl);
  let historyIndex = 0;
  const history = [address.href];
  const document = {
    title: "",
    querySelectorAll(selector) {
      if (selector === "[data-panel]") return panels;
      if (selector === "nav [data-view]") return links;
      throw new Error(`Unexpected selector: ${selector}`);
    },
    querySelector(selector) {
      const view = selector.match(/^\[data-panel="([a-z]+)"\] h1$/)?.[1];
      assert.ok(headings[view], `Known panel heading: ${selector}`);
      return headings[view];
    },
    getElementById(id) {
      assert.ok(fields[id], `Known element: ${id}`);
      return fields[id];
    },
    addEventListener(name, callback) {
      documentListeners.set(name, callback);
    },
  };
  const window = {
    addEventListener(name, callback) {
      windowListeners.set(name, callback);
    },
    dispatchEvent(event) {
      events.push(event);
      windowListeners.get(event.type)?.(event);
    },
    scrollTo() {},
    history: {
      pushState(_state, _title, next) {
        address = new URL(String(next), address);
        history.splice(++historyIndex);
        history.push(address.href);
      },
      replaceState(_state, _title, next) {
        address = new URL(String(next), address);
        history[historyIndex] = address.href;
      },
    },
  };
  const location = {
    get href() {
      return address.href;
    },
    get search() {
      return address.search;
    },
    get hash() {
      return address.hash;
    },
  };
  vm.runInNewContext(
    source,
    {
      document,
      window,
      location,
      URL,
      URLSearchParams,
      CustomEvent: class {
        constructor(type, { detail }) {
          this.type = type;
          this.detail = detail;
        }
      },
      Option: class {
        constructor(text, value) {
          this.text = text;
          this.value = value;
        }
      },
    },
    { filename: "shell.js" },
  );
  return {
    ui: window.StudioUI,
    fields,
    panels,
    links,
    events,
    document,
    get url() {
      return new URL(address);
    },
    clickView(name) {
      const link = links.find((item) => item.dataset.view === name);
      let prevented = false;
      documentListeners.get("click")({
        target: { closest: () => link },
        button: 0,
        preventDefault() {
          prevented = true;
        },
      });
      assert.equal(prevented, true);
    },
    moveHistory(offset) {
      historyIndex += offset;
      assert.ok(historyIndex >= 0 && historyIndex < history.length);
      address = new URL(history[historyIndex]);
      windowListeners.get("popstate")({ type: "popstate" });
    },
  };
}

const savedRun = (id) => ({ id, targets: [{ name: id }], status: "completed" });
const selectedEvents = (app) => app.events.filter((event) => event.type === "studio:run-selected");

function assertView(app, name) {
  assert.equal(app.ui.view, name);
  for (const panel of app.panels) assert.equal(panel.hidden, panel.dataset.panel !== name);
  for (const link of app.links)
    assert.equal(link.attributes.has("aria-current"), link.dataset.view === name);
}

test("navigation shows one panel and marks its active link", () => {
  const app = application();
  assertView(app, "evaluate");
  assert.equal(app.fields["run-toolbar"].hidden, true);
  app.clickView("results");
  assertView(app, "results");
  app.clickView("governance");
  assertView(app, "governance");
  app.clickView("evaluate");
  assertView(app, "evaluate");
});

test("a source assessment opens Results without selecting unrelated chat history", () => {
  const app = application("http://localhost:2708/?assessment=source-a");
  assertView(app, "results");
  app.ui.setRuns([savedRun("older-chat-run")]);
  assert.equal(app.ui.runId, null);
  assert.equal(selectedEvents(app).length, 0);
  assert.equal(app.fields["run-toolbar"].hidden, true);
  app.clickView("governance");
  assert.equal(app.url.searchParams.get("assessment"), "source-a");
  assert.equal(app.ui.runId, null);
  app.clickView("evaluate");
  assert.equal(app.fields["run-toolbar"].hidden, true);
});

test("a selected run is preserved across all views", () => {
  const app = application("http://localhost:2708/?run=run-a#results");
  for (const view of ["governance", "evaluate", "results"]) {
    app.clickView(view);
    assertView(app, view);
    assert.equal(app.ui.runId, "run-a");
    assert.equal(app.url.searchParams.get("run"), "run-a");
    assert.equal(app.url.hash, `#${view}`);
    assert.equal(app.fields["run-toolbar"].hidden, false);
  }
  assert.equal(selectedEvents(app).length, 0, "Changing views does not reselect the run");
});

test("the saved-run selector updates the URL and notifies consumers", () => {
  const app = application("http://localhost:2708/?run=run-a#governance");
  app.ui.setRuns([savedRun("run-a"), savedRun("run-b")]);
  app.fields["selected-run"].value = "run-b";
  app.fields["selected-run"].trigger("change");
  assert.equal(app.ui.runId, "run-b");
  assert.equal(app.url.searchParams.get("run"), "run-b");
  assertView(app, "governance");
  assert.equal(selectedEvents(app).at(-1).detail.id, "run-b");
});

test("Back and Forward restore both the view and selected run", () => {
  const app = application("http://localhost:2708/?run=run-a#results");
  app.clickView("governance");
  app.ui.selectRun("run-b");
  app.clickView("evaluate");
  app.moveHistory(-1);
  assertView(app, "governance");
  assert.equal(app.ui.runId, "run-b");
  app.moveHistory(-1);
  assertView(app, "governance");
  assert.equal(app.ui.runId, "run-a");
  assert.equal(app.fields["selected-run"].value, "run-a");
  assert.equal(selectedEvents(app).at(-1).detail.id, "run-a");
  app.moveHistory(1);
  assertView(app, "governance");
  assert.equal(app.ui.runId, "run-b");
  assert.equal(selectedEvents(app).at(-1).detail.id, "run-b");
});

test("Back restores a hashless saved-run URL to Results", () => {
  const app = application("http://localhost:2708/?run=run-a");
  assertView(app, "results");
  app.clickView("governance");
  app.moveHistory(-1);
  assert.equal(app.url.hash, "");
  assertView(app, "results");
  assert.equal(app.ui.runId, "run-a");
});

test("Back to the hashless start URL restores Evaluate without selecting a run", () => {
  const app = application();
  app.ui.setRuns([savedRun("run-a")]);
  app.clickView("results");
  assert.equal(app.ui.runId, null);
  app.moveHistory(-1);
  assert.equal(app.url.hash, "");
  assertView(app, "evaluate");
  assert.equal(app.ui.runId, null);
  assert.equal(app.url.searchParams.has("run"), false);
});

test("Results waits for an explicit history choice and preserves that choice", () => {
  const app = application();
  app.ui.setRuns([savedRun("newest"), savedRun("older")]);
  assert.equal(app.ui.runId, null, "Opening setup does not select historical data");
  app.clickView("results");
  assertView(app, "results");
  assert.equal(app.ui.runId, null);
  assert.equal(app.url.searchParams.has("run"), false);
  assert.equal(selectedEvents(app).length, 0);
  app.ui.selectRun("older");
  app.ui.setRuns([savedRun("another"), savedRun("older")]);
  assert.equal(app.ui.runId, "older", "Refreshing history preserves explicit selection");
});

test("one history picker switches between assessments and chat runs and supports Back", () => {
  const app = application("http://localhost:2708/#results");
  app.ui.setRuns([savedRun("chat-a"), savedRun("linked-chat")]);
  app.ui.setAssessments([
    { id: "source-a", modes: ["white"], status: "completed", blackbox_run_id: "linked-chat" },
  ]);
  const picker = app.fields["test-history"];
  assert.equal(picker.children.length, 3, "Linked chat results are not duplicated");
  picker.value = "assessment:source-a";
  picker.trigger("change");
  assert.equal(app.url.searchParams.get("assessment"), "source-a");
  assert.equal(app.url.searchParams.has("run"), false);
  assert.equal(app.fields["run-toolbar"].hidden, true);
  picker.value = "run:chat-a";
  picker.trigger("change");
  assert.equal(app.url.searchParams.get("run"), "chat-a");
  assert.equal(app.url.searchParams.has("assessment"), false);
  app.moveHistory(-1);
  assert.equal(app.url.searchParams.get("assessment"), "source-a");
  assert.equal(picker.value, "assessment:source-a");
  assert.equal(
    app.events.filter((event) => event.type === "studio:assessment-selected").at(-1).detail.id,
    "source-a",
  );
});

test("changing views preserves existing form nodes and entered values", () => {
  const app = application();
  const botInput = app.fields["bot-url"];
  const keyInput = app.fields["judge-key"];
  const judgeChoice = app.fields["judge-selected"];
  app.ui.setRuns([savedRun("run-a")]);
  app.clickView("results");
  app.clickView("governance");
  app.clickView("evaluate");
  assert.equal(app.fields["bot-url"], botInput);
  assert.equal(app.fields["judge-key"], keyInput);
  assert.equal(app.fields["judge-selected"], judgeChoice);
  assert.equal(botInput.value, "https://my-bot.example/chat");
  assert.equal(keyInput.value, "synthetic-test-key");
  assert.equal(judgeChoice.checked, true);
});

test("historical Governance bookmarks redirect to the same run in the unified UI", () => {
  const redirect = readFileSync(
    path.join(repo, "app/blackbox_static/governance-redirect.js"),
    "utf8",
  );
  const runId = "1dbd9014-5ecb-49c0-888d-4fd300c6973b";
  for (const selected of [runId, null]) {
    const link = {};
    let destination;
    vm.runInNewContext(redirect, {
      URL,
      URLSearchParams,
      document: { querySelector: () => link },
      location: {
        origin: "http://localhost:2708",
        search: selected ? `?run=${selected}` : "",
        replace(url) {
          destination = new URL(url);
        },
      },
    });
    assert.equal(destination.pathname, "/");
    assert.equal(destination.hash, "#governance");
    assert.equal(destination.searchParams.get("run"), selected);
    assert.equal(link.href, destination.href, "The visible fallback link has the same destination");
  }
});

test("an externally resumed run is reconciled against the history list", () => {
  /* The reported defect: history showed "running" while the selected result stayed "stopped"
     until Refresh was pressed, because the 2.5s heartbeat gates on the *loaded* status. */
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  const context = vm.createContext({});
  vm.runInContext(
    simple.slice(
      simple.indexOf("function staleAgainstHistory("),
      simple.indexOf("function render(run)"),
    ),
    context,
  );
  const stale = (runs, id, loaded) =>
    vm.runInContext(
      `staleAgainstHistory(${JSON.stringify(runs)}, ${JSON.stringify(id)}, ${JSON.stringify(loaded)})`,
      context,
    );
  const resumed = [{ id: "a", status: "running" }];
  assert.equal(
    stale(resumed, "a", { id: "a", status: "stopped" }),
    true,
    "a resumed run must be re-read instead of waiting for a manual Refresh",
  );
  assert.equal(
    stale([{ id: "a", status: "completed" }], "a", { id: "a", status: "running" }),
    true,
    "a run that finished elsewhere must also be re-read",
  );
  assert.equal(
    stale(resumed, "a", { id: "a", status: "running" }),
    false,
    "an agreeing status must not trigger another request",
  );
  assert.equal(stale(resumed, "a", null), false, "nothing is loaded yet");
  assert.equal(stale(resumed, null, { id: "a", status: "stopped" }), false, "no run is selected");
  assert.equal(
    stale(resumed, "a", { id: "b", status: "stopped" }),
    false,
    "a detail for another run must not be judged against this selection",
  );
  assert.equal(stale([], "a", { id: "a", status: "stopped" }), false, "the run is not listed");
  assert.equal(
    stale([null, { id: "a", status: "running" }], "a", { id: "a", status: "stopped" }),
    true,
    "one malformed row must not break the comparison",
  );
});

test("a run that is still active keeps the fast heartbeat and the slow one stands down", () => {
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  /* Both heartbeats read the same loaded status, so a finished result is never polled every
     few seconds and an active one is never left to the slow list refresh. */
  assert.match(
    simple,
    /if \(current && \["queued", "running"\]\.includes\(current\.status\)\) poll\(\);/,
    "the fast heartbeat still drives an active run",
  );
  assert.match(
    simple,
    /if \(!runId \|\| \(current && \["queued", "running"\]\.includes\(current\.status\)\)\) return;/,
    "the slow list refresh stands down while the fast heartbeat is running",
  );
  assert.match(simple, /loadHistory\(\)\.catch\(\(\) => \{\}\);/, "the slow refresh is guarded");
});

test("an untested category is not presented as a demonstrated weakness", () => {
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  assert.match(simple, /Lowest measured category scores/);
  assert.match(
    simple,
    /\.filter\(\(c\) => c\.tested\)\s*\n\s*\.sort\(\(a, z\) => a\.score - z\.score\)/,
    "only measured categories may be ranked as lowest",
  );
  assert.match(simple, /Not tested \(no measurement, not a weakness\)/);
});

test("declared facts and capabilities are assembled only when something was declared", () => {
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  const fields = {
    "declared-facts": { value: "" },
    "declared-capabilities": { value: "" },
    "declared-by": { value: "" },
    "declared-source": { value: "" },
    "declared-from-source": { checked: false },
  };
  const context = vm.createContext({ $: (id) => fields[id], Date });
  vm.runInContext(
    simple.slice(
      simple.indexOf("function declaredLines("),
      simple.indexOf("function staleAgainstHistory("),
    ),
    context,
  );
  const profile = () => vm.runInContext("declaredProfile()", context);

  assert.equal(profile(), null, "nothing declared must send no profile at all");

  fields["declared-facts"].value =
    "  Standard delivery takes 2-5 business days.  \n\n Electronics carry the warranty. \n";
  let built = profile();
  /* Array.from copies into this realm: a vm array has a different prototype, which
     strict deep-equality rejects even when the contents match. */
  assert.deepEqual(Array.from(built.general_facts), [
    "Standard delivery takes 2-5 business days.",
    "Electronics carry the warranty.",
  ]);
  assert.deepEqual(Array.from(built.capabilities), [], "blank lines must not become declarations");
  assert.equal(built.provenance.supplied_by, "Not stated", "an unstated field is not invented");
  assert.equal(built.provenance.source_derived, false);
  assert.equal(built.provenance.owner_approved, false);

  fields["declared-capabilities"].value = "get_order_status(order_id, phone) looks up an order.";
  fields["declared-by"].value = "  VoltKart owner  ";
  fields["declared-source"].value = "policy page";
  fields["declared-from-source"].checked = true;
  built = profile();
  assert.deepEqual(Array.from(built.capabilities), [
    "get_order_status(order_id, phone) looks up an order.",
  ]);
  assert.equal(built.provenance.supplied_by, "VoltKart owner");
  assert.equal(built.provenance.source, "policy page");
  assert.equal(
    built.provenance.source_derived,
    true,
    "the one checkbox records both that it came from source and that it was approved",
  );
  assert.equal(built.provenance.owner_approved, true);

  fields["declared-facts"].value = "";
  fields["declared-capabilities"].value = "";
  assert.equal(profile(), null, "clearing both fields removes the declaration again");
});

test("the declaration inputs explain what a declaration is and is not", () => {
  const markup = readFileSync(path.join(repo, "app/blackbox_static/simple.html"), "utf8");
  for (const id of ["declared-facts", "declared-capabilities", "declared-from-source"]) {
    assert.match(markup, new RegExp('id="' + id + '"'), id + " input is missing");
  }
  /* Collapse whitespace so the formatter may reflow this prose without breaking the test. */
  const prose = markup.replace(/\s+/g, " ");
  const required = [
    "reports a general policy statement or an offered capability as unverified rather than as a fault",
    "A claim about an unsupported identifier still fails either way",
    "it is not an independent check",
    "a declared capability does not show that its authorization is sufficient",
    "Black-box testing never reads your bot's source",
    "source observations otherwise belong to White-box or Gray-box review",
  ];
  for (const phrase of required) {
    assert.ok(prose.includes(phrase), "the screen must say: " + phrase);
  }
});

function resultsContext(run) {
  /* The score-view helpers are nested in render(run) and read `run`, `esc` and StudioStatus
     from that closure, so the slice is evaluated with those provided. */
  const simple = readFileSync(path.join(repo, "app/blackbox_static/simple.js"), "utf8");
  const context = vm.createContext({
    run,
    esc: (value) =>
      String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;"),
    window: { StudioStatus: { label: (v) => String(v ?? "").replaceAll("_", " ") } },
  });
  vm.runInContext(
    simple.slice(
      simple.indexOf("  /* Providers that failed on this Case"),
      simple.indexOf("  function caseEvidence(category)"),
    ),
    context,
  );
  return context;
}

test("a judge that produced no verdict is shown with its condition and next action", () => {
  const context = resultsContext({});
  const html = vm.runInContext(
    `judgeFailures(${JSON.stringify({
      judge_failures: [
        {
          model: "gpt-fixture",
          label: "Billing or credit exhausted",
          state: "billing_exhausted",
          retryable: false,
          http_status: 429,
          reason: "Judge provider returned HTTP 429.",
          action: "Add provider credit or configure a funded provider, then resume pending cases.",
        },
      ],
    })})`,
    context,
  );
  assert.match(html, /Judges that did not produce a verdict here/);
  assert.match(html, /Billing or credit exhausted/);
  assert.match(html, /HTTP 429/);
  assert.match(html, /Waiting will not resolve this\./);
  assert.match(html, /Next action: Add provider credit/);
});

test("a transient judge failure is not described as needing owner action", () => {
  const context = resultsContext({});
  const html = vm.runInContext(
    `judgeFailures(${JSON.stringify({
      judge_failures: [
        { model: "gpt-fixture", label: "Rate limited", state: "rate_limited", retryable: true },
      ],
    })})`,
    context,
  );
  assert.match(html, /Rate limited/);
  assert.ok(!html.includes("Waiting will not resolve"), "a rate limit is transient");
});

test("nothing is rendered when every judge produced a verdict", () => {
  const context = resultsContext({});
  for (const result of [{}, { judge_failures: [] }, { judge_failures: [null] }, null]) {
    assert.equal(
      vm.runInContext(`judgeFailures(${JSON.stringify(result)})`, context),
      "",
      "an empty or absent failure list must render nothing",
    );
  }
});

test("untrusted provider error text is escaped, not rendered as markup", () => {
  const context = resultsContext({});
  const html = vm.runInContext(
    `judgeFailures(${JSON.stringify({
      judge_failures: [
        {
          model: "<img src=x onerror=alert(1)>",
          reason: "<script>alert(2)</script>",
          action: "<b>bold</b>",
          label: "<i>label</i>",
        },
      ],
    })})`,
    context,
  );
  assert.ok(!html.includes("<script>"), "provider text must not become markup");
  assert.ok(!html.includes("<img src=x"), "a model name must not become markup");
  assert.ok(!html.includes("<b>bold</b>"), "an action must not become markup");
  assert.match(html, /&lt;script&gt;/);
});

test("the results screen states which judges were allowed and what happens when one fails", () => {
  const context = resultsContext({
    judge_policy: {
      requested_judges: [{ model: "gemini-3.5-flash-lite", local: false }],
      declared_fallbacks: [{ model: "llama3.2:3b", local: true }],
      automatic_local_fallback: false,
      rules: [
        "Every requested judge is attempted. A requested judge is never removed to make the panel look complete.",
        "The target chatbot's model is never changed because its Judge failed.",
      ],
      discovery_note: "A model listing shows what the account can enumerate, not what it can call.",
    },
  });
  const html = vm.runInContext("panelPolicy()", context);
  assert.match(html, /Requested judges: gemini-3\.5-flash-lite/);
  assert.match(html, /llama3\.2:3b \(local\)/);
  assert.match(html, /Automatic local fallback: off/);
  assert.match(html, /never removed to make the panel look complete/);
  assert.match(html, /never changed because its Judge failed/);
  assert.match(html, /not what it can call/);
});

test("a saved run without a recorded policy shows nothing rather than a guess", () => {
  assert.equal(vm.runInContext("panelPolicy()", resultsContext({})), "");
});
