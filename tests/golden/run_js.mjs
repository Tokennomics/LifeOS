/* Golden parity runner for Travel Mode's core.
 *
 * Runs surfaces/app/www/horizon-core.js against tests/golden/cases.json and
 * compares to the same expected outputs the Python suite checks. Exits non-zero
 * on any drift, printing the offending case — so the phone build can never
 * silently diverge from the server. Invoked by tests/test_golden.py under pytest
 * (and directly in CI).
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const Core = (await import(path.join(here, "..", "..", "surfaces", "app", "www", "horizon-core.js"))).default;
const cases = JSON.parse(fs.readFileSync(path.join(here, "cases.json"), "utf8"));

/* Numeric-aware deep equality: JSON has one number type, so 1.0 (Python) and 1
 * (JS) parse identically — but a string compare would spuriously differ. */
function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a === "number" && typeof b === "number") return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  }
  if (a && b && typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => deepEqual(a[k], b[k]));
  }
  return false;
}

let failures = 0;
function check(label, got, exp) {
  if (!deepEqual(got, exp)) {
    failures++;
    console.error("DRIFT: " + label);
    console.error("  expected: " + JSON.stringify(exp));
    console.error("  js got:   " + JSON.stringify(got));
  }
}

for (const c of cases.plan) check("plan/" + c.name, Core.offlinePlan(c.input), c.expected);
for (const c of cases.classify) check("classify/" + c.input.text.slice(0, 32), Core.isProjectIdea(c.input.text), c.expected);
for (const c of cases.retro) check("retro/" + c.input.week + "/" + c.input.tasks.length, Core.retro(c.input.week, c.input.tasks), c.expected);
for (const c of cases.gate) {
  const i = c.input;
  check("gate/" + i.days_used, Core.gateFromCounts(i.days_used, i.logs_recorded, i.retros_completed), c.expected);
}

if (failures) {
  console.error(`\n${failures} golden mismatch(es) — travel.js core drifted from the shared contract.`);
  process.exit(1);
}
console.log("JS core matches all golden fixtures.");
