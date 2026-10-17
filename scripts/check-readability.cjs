const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const path = require("path");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await page.goto("http://127.0.0.1:2708/", { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForFunction(() => document.querySelector("#stats").children.length === 6);
    assert.equal(await page.locator("nav button").count(), 7);
    assert.equal(await page.locator("nav button").first().innerText(), "Overview");
    const info = await page.evaluate(() => ({
      font: getComputedStyle(document.body).fontFamily,
      color: getComputedStyle(document.querySelector(".muted")).color,
      chartLabels: typeof charts !== "undefined" ? charts.durationChart?.data.labels : [],
      text: document.querySelector("#overview").innerText,
    }));
    assert.match(info.font, /Times New Roman/);
    assert(!/[\u00c2\u00c3\u00e2\u00ef]/.test(info.text), "Corrupted glyphs remain on overview");
    assert(
      !/\b[0-9a-f]{6}\b/.test((info.chartLabels || []).join(" ")),
      "Raw run IDs remain on chart",
    );
    assert(info.text.includes("Tests by type"));
    assert(info.text.includes("Platform verification sample"));
    for (const view of [
      "upload",
      "configuration",
      "execution",
      "results",
      "reports",
      "settings",
      "overview",
    ]) {
      await page.locator('nav button[data-view="' + view + '"]').click();
      assert(await page.locator("#" + view).isVisible(), view + " failed to open");
    }
    await page.screenshot({
      path: path.join(__dirname, "../runtime/readability-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.locator('nav button[data-view="configuration"] span').isVisible(),
      "Mobile labels hidden",
    );
    await page.locator('nav button[data-view="configuration"]').click();
    assert(await page.locator("#configuration").isVisible());
    await page.screenshot({
      path: path.join(__dirname, "../runtime/readability-mobile.png"),
      fullPage: true,
    });
    assert.deepEqual(errors, [], "Browser runtime errors");
    console.log(
      JSON.stringify(
        {
          checks:
            "Desktop/mobile navigation, labels, run names, sample names, Times New Roman and JavaScript runtime",
          result: "passed",
          color: info.color,
          runLabels: info.chartLabels,
          browserErrors: errors,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
