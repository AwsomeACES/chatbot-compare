const fs = require("fs");
const path = require("path");
const root = path.resolve(__dirname, "..");
const htmlPath = path.join(root, "app/static/index.html");
let h = fs.readFileSync(htmlPath, "utf8").replace(/^\uFEFF/, "");
// These static English templates contain corrupted decorative glyphs, not user data.
h = h.replace(/[^\x00-\x7F]/g, "");
h = h.replace(
  /<nav>[\s\S]*?<\/nav>/,
  '<nav aria-label="Main navigation">' +
    [
      ["overview", "Overview"],
      ["upload", "Upload project"],
      ["configuration", "Set up tests"],
      ["execution", "Run progress"],
      ["results", "Test results"],
      ["reports", "Download reports"],
      ["settings", "Settings"],
    ]
      .map(
        ([id, name]) =>
          `<button data-view="${id}"${id === "overview" ? ' class="active"' : ""}><span>${name}</span></button>`,
      )
      .join("") +
    "</nav>",
);
h = h
  .replace("Your agents, under the microscope.", "Your chatbot testing overview.")
  .replace("MEASURE. INSPECT. IMPROVE.", "AI AGENT TESTING STUDIO");
h = h
  .replace(/>\s*Upload project<\/button>/g, ">Upload project</button>")
  .replace(">Connecting<", ">Connecting...<");
h = h.replace(/<div class="upload-symbol">[\s\S]*?<\/div>/, '<div class="upload-symbol">ZIP</div>');
h = h
  .replace("> Start testing", "Start testing")
  .replace("> Start Testing", "Start testing")
  .replace(">Start testing", ">Start testing");
h = h.replace(/(<button[^>]*type="submit"[^>]*>)[^<]*Start testing/, "$1Start testing");
h = h.replace(/(<button[^>]*id="closeDetail"[^>]*>)[^<]*/, "$1Close details");
h = h
  .replace("Category breakdown", "Tests by type")
  .replace("Observed results", "Test counts, not scores");
h = h.replace("<h2>Evaluation suites</h2>", "<h2>What each test type checks</h2>");
h = h.replace("How long the test run took (seconds)", "Time taken by each run");
h = h.replace(
  '<div class="stats" id="stats"></div>',
  '<div class="stats" id="stats"></div><p class="help-note">Pass rate = passed tests divided by passed + failed tests. Tests that could not run or need human review are excluded. This is not an overall chatbot quality grade.</p><p id="latestRunContext" class="context-note"></p>',
);
h = h.replace(
  '<div class="chart"><canvas id="categoryChart">',
  '<p class="help-note">Each bar counts recorded cases of that type. A taller bar means more cases, not better quality. The table below shows which passed, failed or need attention.</p><div class="chart"><canvas id="categoryChart">',
);
h = h.replace(
  '<div class="section-heading">',
  '<article class="card"><h2>Results explained by test type</h2><div id="categorySummary"></div></article><div class="section-heading">',
);
h = h.replace(
  "<h2>Time taken by each run</h2>",
  '<h2>Time taken by each run</h2><p class="help-note">Run 1, Run 2 and so on identify saved test sessions in start-time order. Height shows elapsed seconds (60 seconds = 1 minute). This is measured time, not a score.</p>',
);
h = h.replace(
  '<div id="durationFallback" class="empty">No execution history yet.</div></div>',
  '<div id="durationFallback" class="empty">No execution history yet.</div></div><div id="durationDetails"></div>',
);
h = h
  .replace("<th>Score</th>", "<th>Check result (%)</th>")
  .replace("<th>Duration</th>", "<th>Time taken</th>");
h = h
  .replace(
    "<option>needs_review</option>",
    '<option value="needs_review">Needs human review</option>',
  )
  .replace("<option>blocked</option>", '<option value="blocked">Could not run</option>')
  .replace("<option>not_tested</option>", '<option value="not_tested">Not run</option>')
  .replace("<option>passed</option>", '<option value="passed">Passed</option>')
  .replace("<option>failed</option>", '<option value="failed">Failed</option>');
h = h.replace(
  '<div class="filters">',
  '<p class="help-note">Passed: the check met its expectation. Failed: it did not. Could not run: setup or a service was unavailable. Needs human review: evidence requires judgment. Not run: skipped or cancelled. Each scored check is binary (100% or 0%); unscored checks show N/A.</p><div class="filters">',
);
h = h.replace(
  "Maximum test scheduling time (seconds)",
  "Stop sending new performance requests after (seconds)",
);
h = h.replace(
  'value="60"></label>',
  'value="60"><small class="field-help">For example, 60 means one minute. Existing requests can finish or time out. This limit applies to performance tests only.</small></label>',
);
h = h.replace(
  'name="timeout" type="number" min="1" max="60" value="10"></label>',
  'name="timeout" type="number" min="1" max="60" value="10"><small class="field-help">Maximum wait for a response from one API request, in seconds.</small></label>',
);
h = h
  .replace("user s permissions", "user's permissions")
  .replace("users permissions", "user's permissions")
  .replace("runs findings", "run's findings")
  .replace("projects <code>", "project's <code>");
h = h.replace(
  '<link rel="stylesheet" href="/css/style.css">',
  '<link rel="stylesheet" href="/css/style.css"><link rel="stylesheet" href="/css/readable.css?v=2">',
);
h = h
  .replace(
    '<script defer src="/js/dashboard.js"></script>',
    '<script defer src="/js/readable.js?v=2"></script><script defer src="/js/dashboard.js?v=2"></script>',
  )
  .replace('/js/app.js"', '/js/app.js?v=2"');
fs.writeFileSync(htmlPath, h, "utf8");
const appPath = path.join(root, "app/static/js/app.js");
let j = fs.readFileSync(appPath, "utf8").replace(/^\uFEFF/, "");
j = j
  .replaceAll("escapeHtml(p.name)", "escapeHtml(projectName(p))")
  .replace("`Selected: ${p.name}`", "`Selected: ${projectName(p)}`");
j = j.replace(
  "escapeHtml(new Date(r.started_at).toLocaleString())} - ${escapeHtml(r.status)",
  "escapeHtml(runLabel(r))} - ${escapeHtml(statusNames[r.status]||r.status)",
);
j = j.replace(
  "`${r.id} - ${r.status} - ${new Date(r.started_at).toLocaleString()}`",
  "`${runLabel(r)} - ${statusNames[r.status]||r.status}`",
);
j = j.replace(
  "`Reports ready for run ${r.id}. Results include blocked and needs-review findings.`",
  "`Reports ready for ${runLabel(r)}. Includes tests that could not run or need review.`",
);
j = j.replace(
  "textContent=r.stage",
  "textContent=categoryNames[r.stage]||statusNames[r.stage]||r.stage",
);
j = j
  .replace("${r.id.slice(0,8)}", "Case ${all.indexOf(r)+1}")
  .replace("${escapeHtml(r.category)}", "${escapeHtml(categoryNames[r.category]||r.category)}")
  .replace(
    "${escapeHtml(r.status.replace('_',' '))}",
    "${escapeHtml(statusNames[r.status]||r.status)}",
  )
  .replace("${r.duration_ms.toFixed(1)} ms", "${durationLabel(r.duration_ms)}");
j = j.replace(">Inspect</button>", ">View details</button>");
j = j
  .replace("${name}<small>${help}", "${categoryNames[id]||name}<small>${help}")
  .replace('${id}">${name}</option>', '${id}">${categoryNames[id]||name}</option>');
j = j.replace(
  "if(b?.dataset.run)selectRun(b.dataset.run);",
  "if(b?.dataset.run){selectRun(b.dataset.run);show('results');}",
);
j = j.replace(
  "await refresh();}catch(e){notify(e.message);}",
  "await refresh();if(state.runs.length)await selectRun([...state.runs].sort((a,b)=>b.started_at.localeCompare(a.started_at))[0].id);}catch(e){notify(e.message);}",
);
j = j.replace(
  "<p>${escapeHtml(a.architecture_summary)}</p>",
  "<p><strong>${escapeHtml(projectName(p))}</strong></p><p>Original upload filename: ${escapeHtml(p.name)}. ${p.name==='x.zip'?'This is a small platform verification sample created during setup, not your Reliance chatbot.':'The friendly display name does not change your stored source files.'}</p><p>${escapeHtml(a.architecture_summary)}</p>",
);
fs.writeFileSync(appPath, j, "utf8");
console.log("Updated HTML and application labels with explicit UTF-8 encoding.");
