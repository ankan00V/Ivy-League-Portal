/**
 * Emits the shared role vocabulary consumed by the Python classifier.
 *
 * The feed used to ship all ~1500 listings to the browser for one reason: role
 * track was classified client-side and the classifier reads `description`.
 * Description plus extras is 59% of every row, and at 3.36 MB per feed request
 * that alone exhausted a 5.5 GB monthly Postgres egress budget in ~1,600 page
 * loads.
 *
 * Classifying server-side fixes that, but only if both implementations agree.
 * Hand-copying a 120-entry taxonomy into Python guarantees they drift, so the
 * TypeScript source stays the single definition and this script derives the
 * Python side from it. tests/test_role_classification_parity.py re-runs this
 * and fails if the committed JSON is stale.
 *
 * Usage (from frontend/): npx tsx scripts/generate-role-vocabulary.mjs
 * The path alias @/lib/* only resolves against frontend/tsconfig.json, which is
 * why this lives here rather than in the repo-root scripts/ directory.
 */
import { ROLE_OPTIONS } from "../src/lib/role-taxonomy.ts";
import { TECHNICAL_FILTERS, NON_TECHNICAL_FILTERS } from "../src/lib/role-classification.ts";

// Mirrors the sets in role-classification.ts. Kept here rather than exported so
// the TS module's public surface does not grow just to serve codegen.
const TECHNICAL_GROUPS = new Set([
  "Software Engineering", "Data, AI & Research", "Infrastructure & Security", "Core Engineering",
]);
const NON_TECHNICAL_GROUPS = new Set([
  "Business & Operations", "Finance & Accounting", "Marketing & Content", "Sales & Customer",
  "Law & Policy", "Human Resources & Admin", "Media & Creative", "Education & Social Impact",
]);

const pick = (groups) =>
  ROLE_OPTIONS.filter((option) => groups.has(option.group)).map((option) => option.label.toLowerCase());

console.log(JSON.stringify({
  _generated_by: "scripts/generate_role_vocabulary.mjs",
  _do_not_edit: "Regenerate instead. tests/test_role_classification_parity.py enforces this.",
  technical_role_names: pick(TECHNICAL_GROUPS),
  non_technical_role_names: pick(NON_TECHNICAL_GROUPS),
  technical_filters: TECHNICAL_FILTERS,
  non_technical_filters: NON_TECHNICAL_FILTERS,
}, null, 2));
