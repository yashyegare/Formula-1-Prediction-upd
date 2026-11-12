// npm exec -- node scripts/refresh-driver-portraits.mjs
// Keep portraits local: driver selection never depends on a live image API.
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

/** @param {string} name */
const normalize = (name) =>
  name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
const root = new URL("../", import.meta.url);
/** @type {{active_drivers: string[]}} */
const roster = JSON.parse(
  await readFile(new URL("../flask-app/current_roster.json", root), "utf8")
);
/** @param {string | URL} url */
const get = async (url) => {
  const response = await fetch(url, { signal: AbortSignal.timeout(30000) });
  if (!response.ok)
    throw new Error(`Asset source returned HTTP ${response.status}: ${url}`);
  return response;
};
/** @typedef {{full_name: string, headshot_url: string | null}} Driver */
/** @type {Driver[]} */
const current = await (
  await get("https://api.openf1.org/v1/drivers?session_key=latest")
).json();
/** @type {Driver[]} */
const previous = await (
  await get("https://api.openf1.org/v1/drivers?session_key=9839")
).json();
/** @type {Record<string, string>} */
const aliases = { andreakimiantonelli: "kimiantonelli" };
// OpenF1 has no headshot for this recent replacement. Use the portrait
// linked by his official FIA F2 profile, keeping its provenance explicit.
/** @type {Record<string, string>} */
const officialFallbacks = {
  rafaelcamara:
    "https://res.cloudinary.com/prod-f2f3/d_common:f2:fallback.webp/c_fill,w_720/q_auto/v1770000000/common/f2/2026/invictaracing/rafcam01/2026invictaracingrafcam01right.webp",
};
/** @param {Buffer} bytes */
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const imageHashes = new Set();
/** @type {Record<string, string>} */
const manifest = JSON.parse(
  await readFile(new URL("src/data/driver-portraits.json", root), "utf8")
);
const sources = [];
await mkdir(new URL("public/drivers/", root), { recursive: true });
await mkdir(new URL("src/data/", root), { recursive: true });
for (const name of roster.active_drivers) {
  const key = normalize(name);
  /** @param {Driver[]} rows */
  const find = (rows) =>
    rows.find(
      (driver) =>
        normalize(driver.full_name) === (aliases[key] ?? key) &&
        driver.headshot_url
    );
  const driver = find(current) ?? find(previous);
  const source = driver?.headshot_url ?? officialFallbacks[key];
  if (!source) throw new Error(`No verified portrait source for ${name}`);
  const url = new URL(source);
  const officialF2 =
    url.hostname === "res.cloudinary.com" &&
    url.pathname.startsWith("/prod-f2f3/");
  if (
    url.protocol !== "https:" ||
    (url.hostname !== "media.formula1.com" && !officialF2)
  )
    throw new Error(`Unexpected portrait host for ${name}`);
  const bytes = Buffer.from(await (await get(url)).arrayBuffer());
  if (imageHashes.has(hash(bytes)))
    throw new Error(`Image source returned a duplicate portrait for ${name}`);
  imageHashes.add(hash(bytes));
  const filename = `${key}.webp`;
  await sharp(bytes)
    .resize(144, 144, { fit: "cover", position: "north" })
    .webp({ quality: 84 })
    .toFile(fileURLToPath(new URL(`public/drivers/${filename}`, root)));
  manifest[key] = `/drivers/${filename}`;
  sources.push({ name, source: url.href });
  console.log(`Prepared ${name}`);
}
await writeFile(
  new URL("src/data/driver-portraits.json", root),
  JSON.stringify(manifest, null, 2) + "\n"
);
await writeFile(
  new URL("public/drivers/sources.json", root),
  JSON.stringify(
    {
      provider:
        "OpenF1 driver metadata; Formula 1 media portraits; official FIA F2 profile for Rafael Camara",
      retrieved: new Date().toISOString(),
      portraits: sources,
    },
    null,
    2
  ) + "\n"
);
console.log(`Prepared ${sources.length} driver portraits.`);
