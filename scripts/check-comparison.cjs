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
    await page.locator("nav [data-view=comparison]").waitFor();
    await page.locator("nav [data-view=comparison]").click();
    await page.waitForFunction(
      () => document.querySelector("#bot-a [data-field=project_id]").options.length > 1,
    );
    for (const side of ["a", "b"])
      assert(!(await page.locator("#bot-" + side + " [data-field=execution_consent]").isChecked()));
    await page.locator("#bot-a [data-copy]").click();
    await page.locator("#comparisonCheck").click();
    await page.waitForFunction(() =>
      document.querySelector("#comparisonReady").textContent.includes("Configuration check only"),
    );
    let posted;
    const fixture = {
      id: "ui-fixture",
      status: "completed",
      a: { name: "<img src=x onerror=alert(1)>" },
      b: { name: "Bot B" },
      runs: { a: null, b: null },
      category_scores: [
        {
          category: "hallucination",
          a: 75,
          b: null,
          matched_scored_cases: 0,
          recorded_pairs: 1,
          source_only: false,
          difference_points: null,
        },
      ],
      paired_score: { a: null, b: null },
      complete_comparison: false,
      summary: "UI test fixture: no winner",
      limitations: ["Synthetic browser verification only"],
      cases: [
        {
          category: "hallucination",
          name: "Fixture case",
          comparable: false,
          a: {
            status: "needs_review",
            score: { percent: 75 },
            actual: { answer: "Visible answer A" },
            explanation: { text: "Fixture explanation" },
          },
          b: {
            status: "blocked",
            score: { percent: null },
            actual: { error: "No answer" },
            explanation: { text: "Missing response" },
          },
        },
      ],
    };
    await page.route("**/api/comparisons", async (route) => {
      if (route.request().method() === "POST") {
        posted = route.request().postDataJSON();
        return route.fulfill({ status: 202, json: { id: fixture.id } });
      }
      return route.fulfill({ json: [] });
    });
    await page.route("**/api/comparisons/ui-fixture", (route) => route.fulfill({ json: fixture }));
    await page.locator("#comparisonStart").click();
    await page.waitForFunction(() =>
      document.querySelector("#comparisonResults").textContent.includes("Visible answer A"),
    );
    assert(posted.a.project_id && posted.b.project_id);
    assert.equal(posted.a.execution_consent, false);
    assert.equal(posted.b.performance_consent, false);
    assert.equal(await page.locator("#comparisonResults img").count(), 0);
    assert.match(await page.locator("#comparisonResults").textContent(), /Not scored/);
    assert.equal(await page.locator("#comparisonResults a").count(), 2);
    await page.setViewportSize({ width: 600, height: 900 });
    assert.equal(
      await page
        .locator("#comparisonBots")
        .evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length),
      1,
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: comparison navigation, independent settings/consent, real readiness, request capture, side-by-side evidence, escaped bot names, download links and mobile layout. Synthetic UI fixtures never persisted; no paid calls.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
