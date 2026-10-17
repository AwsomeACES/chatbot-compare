// Parse maintained JavaScript without executing scripts or contacting bots.
const { readdirSync } = require("node:fs");
const { join } = require("node:path");
const { spawnSync } = require("node:child_process");

function javascriptFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = join(directory, entry.name);
    if (entry.isDirectory()) {
      return ["node_modules", "__pycache__"].includes(entry.name) ? [] : javascriptFiles(file);
    }
    return /\.(?:js|cjs|mjs)$/.test(entry.name) ? [file] : [];
  });
}

const files = ["app/blackbox_static", "scripts", "sample_project"].flatMap(javascriptFiles);
let failed = false;
for (const file of files) {
  const check = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
  if (check.status !== 0) {
    failed = true;
    console.error(`${file}: ${check.stderr || check.error || "Syntax check failed"}`);
  }
}
console.log(`JavaScript syntax: ${files.length} files checked.`);
process.exitCode = failed ? 1 : 0;
