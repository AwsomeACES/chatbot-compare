const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:2708/");
    await page.locator('nav button[data-view="configuration"]').click();
    await page.locator("#testReadiness").waitFor();
    await page.locator("#allTestsPreset").click();
    await page.waitForFunction(
      () => document.querySelectorAll("#testReadiness .readiness-list>div").length === 12,
    );
    assert(await page.locator("#notice").isHidden());
    assert.equal(await page.locator("[name=execution_consent]").isChecked(), false);
    assert.equal(await page.locator("[name=performance_consent]").isChecked(), false);
    assert(
      (await page.locator("#testReadiness").innerText()).includes("Enter the running bot API URL"),
    );
    await page.locator("[name=target_url]").fill("http://127.0.0.1:8000");
    await page.waitForFunction(
      () =>
        !document
          .querySelector("#testReadiness")
          .textContent.includes("Enter the running bot API URL"),
    );
    await page.screenshot({ path: "runtime/judge-readiness.png", fullPage: true });
    await page.locator('nav button[data-view="results"]').click();
    const runs = await (await page.request.get("http://127.0.0.1:2708/api/runs")).json();
    const saved = runs.find((r) => r.results.length);
    assert(saved);
    await page.locator("#runSelect").selectOption(saved.id);
    await page.locator("#resultRows button").first().click();
    assert(await page.locator("#judgeEvidence").isVisible());
    assert(
      (await page.locator("#judgeEvidence").innerText()).includes("Expected answer or behavior"),
    );
    assert((await page.locator("#judgeEvidence").innerText()).includes("Judge assessment"));
    await page.screenshot({ path: "runtime/judge-detail.png" });
    await page.locator("#closeDetail").click();
    await page.evaluate(() => {
      showJudgeDetails({
        input: { prompt_a: "<script>alert(1)</script>", prompt_b: "Equivalent scenario" },
        actual: { a: { answer: "First answer" }, b: { answer: "Second answer" } },
        score: {
          percent: 75,
          basis: "AI rubric estimate",
          criteria: [{ name: "Tone", rating: 3, evidence: "Synthetic UI verification only" }],
        },
        explanation: { text: "Synthetic UI fixture; not a saved evaluation." },
      });
      document.getElementById("detailDialog").showModal();
    });
    assert.equal(await page.locator("#judgeEvidence script").count(), 0);
    assert((await page.locator("#judgeEvidence").innerText()).includes("Response B"));
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.locator("#judgeEvidence").isVisible());
    assert.deepEqual(errors, []);
    console.log(
      "PASS: no select-all banner; 12 live readiness checks; consent untouched; expected/actual and paired judge views; escaped evidence; mobile layout; no JS errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
