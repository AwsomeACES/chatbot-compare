const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  try {
    const p = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    p.on("pageerror", (e) => errors.push(e.message));
    await p.goto("http://127.0.0.1:2708/");
    await p.locator('nav button[data-view="results"]').click();
    await p.waitForFunction(() =>
      document.querySelector("#evaluationSummary").textContent.includes("recorded cases"),
    );
    for (const label of [
      "Hallucination",
      "Bias",
      "Guardrails",
      "Prompt injection",
      "Security checks",
      "Language and tone",
      "White-box",
    ])
      assert((await p.locator("#evaluationSummary").innerText()).includes(label), label);
    assert.equal(await p.locator("#evaluationSummary [data-category]").count(), 12);
    await p.locator("#resultRows button").first().click();
    assert((await p.locator("#detailSummary").innerText()).length > 30);
    await p.locator("#closeDetail").click();
    await p.locator('nav button[data-view="configuration"]').click();
    await p.getByRole("button", { name: "Load editable AI test examples" }).click();
    assert.equal(JSON.parse(await p.locator("[name=dataset]").inputValue()).length, 4);
    assert.equal(await p.locator("[name=judge_consent]").isChecked(), false);
    await p.locator('nav button[data-view="results"]').click();
    await p.screenshot({ path: "runtime/scoring-summary.png", fullPage: true });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: all 12 categories, score summary, case explanations, editable examples, explicit AI consent; no browser errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
