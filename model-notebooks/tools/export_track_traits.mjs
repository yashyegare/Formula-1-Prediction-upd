// Regenerates model-notebooks/datasets/track_traits.json from the Track
// Explorer repo's own geometry code, so the traits in our artifact are the
// explorer's numbers by the explorer's definitions rather than a Python
// re-implementation that would drift from them.
//
//   node model-notebooks/tools/export_track_traits.mjs [path-to-f1-circuits-app]
//
// Needs the explorer checked out next to this repo; the committed JSON is what
// CI and the artifact build read, so nobody else has to have it.

import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { register } from "node:module";

// The explorer is a Vite app: its modules import each other without a .js
// extension, which plain Node rejects.
register("./esm_extensionless.mjs", import.meta.url);

// Anchored to this file, not the cwd: the script is run from the repo root by
// convention but resolves the same wherever it is invoked from.
const repoRoot = resolve(fileURLToPath(import.meta.url), "..", "..", "..");
const explorerDir = resolve(process.argv[2] ?? resolve(repoRoot, "..", "f1-circuits-app"));
const dataFile = resolve(explorerDir, "src/data/circuits.json");
const outFile = resolve(repoRoot, "model-notebooks/datasets/track_traits.json");

const { getTrackDetail } = await import(
  pathToFileURL(resolve(explorerDir, "src/utils/track3d.js")).href
);

const circuits = JSON.parse(readFileSync(dataFile, "utf8"));

let commit = "unknown";
try {
  commit = execFileSync("git", ["-C", explorerDir, "rev-parse", "--short", "HEAD"],
    { encoding: "utf8" }).trim();
} catch {
  // git missing or the explorer isn't a checkout — provenance degrades to "unknown"
}

const traits = {};
for (const circuit of circuits) {
  const detail = getTrackDetail(circuit);
  traits[circuit.id] = {
    name: circuit.name,
    cornerCount: detail.corners.length,
    direction: detail.direction,
    longestStraightMeters: Math.round(detail.longestStraightMeters),
    lengthMeters: Math.round(detail.lengthMeters),
    altitudeMeters: circuit.altitude ?? null,
    drsZones: circuit.drsZones ?? null,
    continent: circuit.continent ?? null,
    firstGp: circuit.firstgp ?? null,
  };
}

writeFileSync(outFile, JSON.stringify({
  source: {
    repo: "F1TrackMetricsLab (Track Explorer)",
    commit,
    file: "src/data/circuits.json",
    derived_by: "src/utils/track3d.js getTrackDetail()",
    generated_at: new Date().toISOString().slice(0, 10),
  },
  caveat: "Corner count, spin direction and longest straight are read off the "
    + "circuit's outline polyline, not surveyed or engineering data — the "
    + "explorer labels them a stylised read of track shape.",
  traits,
}, null, 1) + "\n", "utf8");

console.log(`${Object.keys(traits).length} circuits -> ${outFile} (explorer ${commit})`);
