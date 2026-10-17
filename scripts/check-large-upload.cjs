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
    await page.locator('nav button[data-view="upload"]').click();
    await page.waitForFunction(() => document.querySelector("#uploadLimit").textContent === "1024");
    await page.evaluate(() => uploadZip({ name: "too-large.zip", size: 1025 * 1048576 }));
    assert.match(await page.locator("#uploadStatus").innerText(), /Maximum upload size is 1024/);
    const responsePromise = page.waitForResponse(
      (r) => r.url().endsWith("/api/projects/upload") && r.request().method() === "POST",
      { timeout: 180000 },
    );
    await page.locator("#zipInput").setInputFiles(process.argv[2] || "D:/reliance-project.zip");
    const response = await responsePromise;
    assert.equal(response.status(), 201, await response.text());
    const project = await response.json();
    await page.waitForFunction(
      () => document.querySelector("#uploadStatus").textContent.startsWith("Ready:"),
      { timeout: 30000 },
    );
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify({
        status: "passed",
        archive: project.name,
        bytes: project.size,
        validation: project.validation,
        browserErrors: errors,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
