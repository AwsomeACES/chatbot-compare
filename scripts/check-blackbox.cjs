const { chromium } = require("../runtime/ui-check/node_modules/playwright");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://127.0.0.1:2709");
  await page.getByText("System online", { exact: true }).waitFor();
  await page.selectOption("#mode", "compare");
  if (!(await page.locator("#url-1").isVisible())) throw Error("Second target not visible");
  for (const box of await page.locator("#categories input").all()) await box.uncheck();
  await page.fill("#name-0", "Verification: unavailable fixture A");
  await page.fill("#name-1", "Verification: unavailable fixture B");
  await page.locator('#categories input[value="performance"]').check();
  await page.fill("#url-0", "http://127.0.0.1:65520/chat");
  await page.fill("#url-1", "http://127.0.0.1:65521/chat");
  await page.check("#consent");
  await page.check("#performance-consent");
  await page.click("#start");
  await page.waitForFunction(
    () => document.querySelector("#stage").textContent.startsWith("completed"),
    { timeout: 30000 },
  );
  await page.locator("#results").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "runtime/reports/blackbox-ui-verification.png", fullPage: true });
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "UI PASS: both targets, case selection, unavailable targets, completed progress and results; no JavaScript errors.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
