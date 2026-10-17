/* Run with node --test scripts/test-studio-navigation.cjs. No browser or paid API calls. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const repo = process.env.STUDIO_REPO || path.resolve(__dirname, "..");
const source = readFileSync(path.join(repo, "app/blackbox_static/shell.js"), "utf8");

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
