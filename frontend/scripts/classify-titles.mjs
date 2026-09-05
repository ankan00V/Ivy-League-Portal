/**
 * Classifies newline-delimited JSON listings from stdin using the TypeScript
 * classifier and prints one track per line. Exists so the Python port can be
 * diffed against the original on real data rather than on hand-picked examples.
 */
import { classifyRoleTrack } from "../src/lib/role-classification.ts";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
for (const line of Buffer.concat(chunks).toString("utf8").split("\n")) {
  if (!line.trim()) continue;
  const row = JSON.parse(line);
  console.log(classifyRoleTrack(row));
}
