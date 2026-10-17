const { chromium } = require("../runtime/ui-check/node_modules/playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const base = "http://127.0.0.1:2708",
    id = "dc363235-db8d-40dd-a46e-c2c40a442f7c";
  await page.goto(base + "/?run=" + id);
  await page.locator("#charts .donut").waitFor();
  assert.equal(await page.locator("#advanced").getAttribute("open"), null);
  assert.equal(await page.locator("#url-0").isVisible(), true);
  assert.equal(await page.locator("#zip-0").isVisible(), true);
  assert.equal(await page.locator("#message-0").isVisible(), false);
  assert.equal(await page.locator("#consent").isChecked(), false);
  assert.equal(await page.locator("#judge-consent").isChecked(), false);
  assert.equal(await page.locator("#performance-consent").isChecked(), false);
  assert.equal(await page.locator("#charts .category-bar").count(), 5);
  assert.equal(await page.locator("#charts .latency-chart").count(), 1);
  assert.match(await page.locator("#charts").innerText(), /149\/150 cases scored/);
  await page.screenshot({ path: "runtime/reports/simple-ui-desktop.png", fullPage: false });
  await page.locator("#charts").screenshot({ path: "runtime/reports/simple-ui-dashboard.png" });
  const saved = await (await page.request.get(base + "/api/blackbox/runs/" + id)).json();
  // Test the polling race with in-browser fixture responses. No benchmark records are written.
  let count = 0;
  const run = structuredClone(saved);
  run.status = "running";
  run.progress = 50;
  await page.route("**/api/blackbox/runs/" + id, (route) => {
    count++;
    const updated = structuredClone(run);
    updated.progress = 50 + count;
    updated.cases[1].results[0].reason += " Progress refresh " + count;
    updated.summary[0].requests += count;
    return route.fulfill({ json: updated });
  });
  await page.reload();
  await page.locator("#cases details").first().waitFor();
  const detail = page.locator("#cases details").first();
  await detail.locator("summary").click();
  const before = await detail.evaluate((el) => el.getBoundingClientRect().top);
  await page.waitForTimeout(4800);
  assert.equal(
    await detail.evaluate((el) => el.open),
    true,
    "Open case must survive progress updates",
  );
  const after = await detail.evaluate((el) => el.getBoundingClientRect().top);
  assert.ok(Math.abs(before - after) < 20, "Open case scroll should stay stable");
  assert.ok(count >= 3, "Expected multiple refreshes");
  await page.unroute("**/api/blackbox/runs/" + id);
  await page.reload();
  await page.locator("#charts .donut").waitFor();
  await page.locator("#search").fill("no-such-transcript-fixture-987");
  assert.equal(await page.locator("#cases details").count(), 0);
  await page.locator("#search").fill("");
  assert.equal(await page.locator("#cases details").count(), 150);
  await page.locator("#mode").selectOption("compare");
  assert.equal(await page.locator("#url-1").isVisible(), true);
  // Exercise compare chart rendering against a copied fixture, without storing fake results.
  await page.evaluate((r) => {
    const other = structuredClone(r.summary[0]);
    other.name = "Browser fixture B";
    r.summary.push(other);
    r.targets.push({ ...r.targets[0], name: "Browser fixture B" });
    r.cases.forEach((c) => c.results.push(structuredClone(c.results[0])));
    window.drawDashboard(r, {});
  }, saved);
  assert.equal(await page.locator("#charts .donut").count(), 2);
  await page.reload();
  await page.locator("#charts .donut").waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "runtime/reports/simple-ui-mobile.png", fullPage: false });
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2),
    "Mobile must not overflow horizontally",
  );
  // Consent validation must occur before trying a target or judge.
  await page.locator("#url-0").fill("http://127.0.0.1:8000");
  await page.locator("#start").click();
  await page.waitForFunction(() =>
    document.getElementById("notice").textContent.includes("Allow test messages"),
  );
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      passed: true,
      checks: [
        "simple form",
        "explicit consent",
        "saved 149/150 results",
        "offline donut/category/latency charts",
        "case remains open across polls",
        "scroll stability",
        "search",
        "compare charts",
        "mobile layout",
        "actionable start validation",
      ],
      browserErrors: errors,
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
