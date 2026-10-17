const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:2708/");
    await page.locator("#testReadiness").waitFor({ state: "attached" });
    await page.locator('nav button[data-view="configuration"]').click();
    const provider = page.locator("[name=judge_provider]");
    assert.deepEqual(await provider.locator("option").evaluateAll((es) => es.map((x) => x.value)), [
      "openai",
      "claude",
      "gemini",
    ]);
    await provider.selectOption("claude");
    await page.locator("[name=api_key]").fill("dummy-key-for-ui-check");
    await page.locator("[name=model]").fill("dummy-model");
    await provider.selectOption("gemini");
    assert.equal(await page.locator("[name=api_key]").inputValue(), "");
    assert.equal(await page.locator("[name=model]").inputValue(), "");
    await page.locator("[name=request_defaults]").fill('{"provider":"gemini"}');
    assert.equal(await page.evaluate(() => evaluationConfig().request_defaults.provider), "gemini");
    await page.locator("#checkJudge").click();
    await page.waitForFunction(() =>
      document.querySelector("#judgeConnection").textContent.includes("consent"),
    );
    assert.equal(await page.locator("[name=judge_consent]").isChecked(), false);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: Claude/Gemini selectors, cross-provider key clearing, separate bot defaults, consent-gated connection check; no browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
