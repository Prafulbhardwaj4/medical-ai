// Vercel build command: node scripts/stamp-version.js
// Writes version.json and bakes the same id into js/update-check.js.
// Runs only on Vercel (or with --force) so local files stay untouched.
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
if (!process.env.VERCEL && !process.argv.includes("--force")) {
  console.log("[stamp-version] not on Vercel, skipping (use --force to test)");
  process.exit(0);
}

const id =
  (process.env.VERCEL_GIT_COMMIT_SHA || "").slice(0, 12) ||
  process.env.VERCEL_DEPLOYMENT_ID ||
  "t" + Date.now();

const file = path.join(root, "js", "update-check.js");
const src = fs.readFileSync(file, "utf8");
const re = /var MS_BUILD_ID = "[^"]*";/;
if (!re.test(src)) {
  console.error("[stamp-version] MS_BUILD_ID line not found in js/update-check.js");
  process.exit(1); // fail the deploy rather than ship an unstamped build
}
fs.writeFileSync(file, src.replace(re, `var MS_BUILD_ID = "${id}";`));
fs.writeFileSync(
  path.join(root, "version.json"),
  JSON.stringify({ v: id, t: new Date().toISOString() }) + "\n"
);
console.log("[stamp-version] build id:", id);