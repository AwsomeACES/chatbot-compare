const { chromium } = require("../runtime/ui-check/node_modules/playwright");
(async () => {
  const b = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  });
  const p = await b.newPage({ viewport: { width: 1500, height: 1000 } });
  let errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto("http://127.0.0.1:2708");
  await p.getByText("System online", { exact: true }).waitFor();
  for (const name of [
    "Hallucination testing (answer accuracy)",
    "Bias testing (fairness)",
    "Guardrails testing (safety policy)",
    "Performance testing (speed and reliability)",
  ]) {
    const box = p.getByRole("checkbox", { name, exact: false });
    if ((await box.count()) !== 1 || !(await box.isChecked()))
      throw Error("Missing or unselected category: " + name);
  }
  await p.locator("#categories").screenshot({ path: "runtime/reports/clear-category-labels.png" });
  const perf = p
    .locator("label.suite-card")
    .filter({ has: p.locator('input[value="performance"]') });
  if (!(await perf.innerText()).includes("No AI judge is needed"))
    throw Error("Missing performance guidance");
  await p.getByText("Local AI judge and execution settings", { exact: true }).click();
  await p.fill("#count", "40");
  await p.locator("#count").dispatchEvent("change");
  if (!(await perf.innerText()).includes("40 planned cases")) throw Error("Case count not updated");
  if (errors.length) throw Error(errors.join("\n"));
  console.log(
    "PASS: all four category names visible, selected, described and showing live case counts; no JavaScript errors.",
  );
  await b.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
