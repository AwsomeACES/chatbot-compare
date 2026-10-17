const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.goto("http://127.0.0.1:2708/");
    await page.locator("#prepareEasy").waitFor({ state: "attached" });
    await page.locator('nav [data-view="configuration"]').click();
    const cases = ["hallucination", "bias", "guardrails", "functional"].map((category) => ({
      category,
      name: "UI import fixture",
      prompt: "Synthetic UI-only fixture",
    }));
    await page.locator("#datasetFile").setInputFiles({
      name: "fixture.json",
      mimeType: "application/json",
      buffer: Buffer.from("\ufeff" + JSON.stringify(cases)),
    });
    await page.waitForFunction(
      () => document.querySelector("[name=category][value=hallucination]").checked,
    );
    for (const c of cases)
      assert(await page.locator(`[name=category][value=${c.category}]`).isChecked());
    assert.match(await page.locator("#notice").textContent(), /4 cases imported/);
    const result = await page.evaluate(async () => {
      const saved = { api, renderRun, refresh };
      let switched = 0;
      api = async () => ({ id: "fixture-run", status: "completed" });
      renderRun = () => {};
      refresh = async () => {
        switched++;
      };
      state.run = { id: "fixture-run" };
      state.runs = [{ id: "unrelated-newer-run", started_at: "2099-01-01" }];
      await pollRun("fixture-run");
      const id = state.run.id;
      state.run = { id: "user-selected-another-run" };
      await pollRun("fixture-run");
      const stale = state.run.id;
      api = saved.api;
      renderRun = saved.renderRun;
      refresh = saved.refresh;
      return { id, stale, switched };
    });
    assert.deepEqual(result, {
      id: "fixture-run",
      stale: "user-selected-another-run",
      switched: 1,
    });
    console.log(
      "PASS: BOM JSON import selects all dataset categories; polling preserves run identity and ignores stale responses. No evaluation submitted.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
