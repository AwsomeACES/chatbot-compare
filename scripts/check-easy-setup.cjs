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
    await page.locator("#prepareEasy").waitFor({ state: "attached" });
    await page.locator('nav [data-view="configuration"]').click();
    await page.locator("#easyBot").selectOption("reliance");
    await page.locator("[name=request_defaults]").fill('{"provider":"gemini"}');
    await page.locator("#prepareEasy").click();
    const config = await page.evaluate(() => evaluationConfig());
    assert.equal(config.dataset.length, 8);
    assert.equal(config.dataset.filter((c) => c.category === "bias").length, 3);
    assert.equal(config.dataset.filter((c) => c.category === "multiturn").length, 2);
    assert.equal(config.dataset.filter((c) => c.category === "language").length, 3);
    assert.equal(config.history_field, "history");
    assert.equal(config.iterations, 10);
    assert.equal(config.concurrency, 1);
    assert.equal(config.request_defaults.provider, "gemini");
    assert(!config.judge_consent && !config.performance_consent && !config.execution_consent);
    for (const cat of ["bias", "multiturn", "language", "performance"])
      assert(config.categories.includes(cat));
    await page.locator("#prepareEasy").click();
    assert.equal(await page.evaluate(() => evaluationConfig().dataset.length), 8);
    await page
      .locator("[name=dataset]")
      .fill('[{"category":"bias","name":"My existing case","prompt_a":"A","prompt_b":"B"}]');
    await page.locator("#prepareEasy").click();
    assert.equal(
      await page.evaluate(
        () => evaluationConfig().dataset.filter((c) => c.category === "bias").length,
      ),
      1,
    );
    await page.locator("[name=dataset]").fill("invalid");
    await page.locator("#prepareEasy").click();
    assert.match(await page.locator("#easyResult").textContent(), /Setup not applied/);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: eight starter cases, preserved existing cases/provider, repeat-safe preparation, invalid JSON feedback, four categories, safe workload and unchanged consents. No browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
