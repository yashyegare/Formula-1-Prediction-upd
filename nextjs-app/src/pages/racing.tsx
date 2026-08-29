import { type NextPage } from "next";
import Head from "next/head";
import Link from "next/link";
import { useEffect, useRef, useState, useCallback } from "react";

/* ═══════════════════════════════════════════════
   TRACK DATA — realistic F1 circuit centerlines
   ═══════════════════════════════════════════════ */

interface TrackDef {
  name: string;
  country: string;
  flag: string;
  length: string;
  accent: string;
  /** Centerline points — the track is drawn around these */
  centerline: [number, number][];
  /** Track half-width in px */
  halfWidth: number;
  /** Par time in ms for scoring */
  parTime: number;
  /** AI racing line (offset from centerline for realism) */
  aiLine?: [number, number][];
}

// Helper to offset a centerline to create AI line
function offsetLine(pts: [number, number][], dx: number, dy: number): [number, number][] {
  return pts.map(([x, y]) => [x + dx, y + dy]);
}

// ─── Real GPS-traced circuit centerlines (bacinger/f1-circuits, MIT licensed) ───
// Projected from official circuit GPS LineStrings, not hand-estimated.

const MONACO_CENTERLINE: [number, number][] = [
  [394.0, 134.2], [394.2, 126.8], [398.6, 118.6], [441.4, 61.0], [444.9, 60.0], [452.1, 63.6], [456.8, 81.7], [469.6, 99.6], [474.2, 94.4], [461.3, 78.8], [461.6, 69.7], [484.2, 61.4], [492.4, 62.5], [492.5, 92.8], [484.3, 136.3], [471.8, 162.2], [449.6, 188.3], [397.8, 215.4], [383.3, 220.5], [340.6, 229.1], [337.9, 237.4], [334.8, 238.5], [322.8, 236.3], [239.1, 248.2], [233.0, 257.9], [226.3, 277.1], [225.0, 300.9], [226.3, 307.2], [238.0, 319.5], [245.9, 363.5], [244.4, 367.8], [238.2, 371.4], [238.1, 378.2], [244.8, 396.4], [253.8, 410.6], [260.9, 417.8], [274.8, 424.8], [278.0, 431.5], [274.5, 435.8], [256.3, 439.9], [248.2, 439.4], [244.3, 436.1], [242.5, 426.1], [227.4, 404.4], [212.1, 352.8], [206.5, 293.5], [213.6, 243.2], [224.0, 238.3], [259.4, 233.8], [299.3, 222.4], [321.3, 219.6], [357.4, 203.8], [397.3, 195.6], [410.5, 184.8], [415.5, 173.8], [415.2, 167.9], [409.1, 150.4], [396.0, 138.8], [394.0, 134.2]
];

const SILVERSTONE_CENTERLINE: [number, number][] = [
  [371.6, 63.6], [420.3, 60.4], [429.6, 64.8], [436.8, 75.7], [447.3, 121.1], [450.3, 174.5], [459.9, 194.9], [451.5, 229.2], [452.5, 234.5], [462.0, 248.7], [463.8, 258.4], [458.4, 268.3], [435.9, 283.8], [371.8, 401.3], [355.3, 427.0], [346.9, 436.6], [333.7, 439.7], [321.6, 434.1], [308.2, 409.4], [271.6, 366.5], [267.7, 365.2], [256.3, 373.2], [249.2, 369.5], [239.9, 356.4], [236.2, 342.6], [241.3, 332.7], [301.9, 253.8], [308.2, 248.5], [317.0, 247.2], [347.9, 250.8], [359.2, 248.6], [395.6, 220.8], [402.8, 217.9], [407.6, 222.1], [414.6, 243.6], [419.5, 245.4], [424.1, 241.8], [430.7, 222.8], [430.4, 204.7], [325.3, 108.2], [314.0, 103.8], [304.0, 106.8], [301.0, 112.3], [297.7, 132.7], [291.5, 137.3], [282.8, 136.7], [276.0, 129.0], [276.4, 122.2], [292.1, 90.4], [311.2, 72.8], [322.6, 68.5], [371.6, 63.6]
];

const SUZUKA_CENTERLINE: [number, number][] = [
  [555.3, 260.6], [636.8, 360.3], [639.9, 376.1], [634.4, 395.0], [625.9, 403.6], [616.1, 404.7], [606.3, 399.2], [576.8, 354.0], [572.1, 350.0], [549.3, 347.6], [538.3, 342.6], [533.3, 334.3], [527.5, 312.5], [521.3, 302.1], [511.2, 296.2], [483.8, 293.6], [474.2, 287.6], [468.5, 277.0], [467.5, 267.2], [477.0, 233.8], [471.5, 220.9], [459.3, 213.4], [444.4, 206.6], [432.0, 203.9], [411.8, 205.5], [393.3, 214.4], [385.1, 221.1], [349.9, 262.9], [303.3, 267.2], [299.4, 262.2], [292.9, 234.7], [282.9, 175.1], [284.2, 166.0], [295.2, 139.5], [291.4, 134.1], [284.1, 135.3], [260.0, 174.0], [246.2, 186.6], [233.2, 192.0], [202.2, 193.6], [181.4, 188.4], [161.6, 180.3], [142.1, 165.7], [126.8, 144.5], [111.6, 106.5], [105.2, 98.4], [94.7, 95.2], [75.2, 97.6], [64.2, 103.9], [61.2, 108.7], [60.4, 119.3], [67.0, 131.9], [90.2, 152.2], [124.4, 175.7], [162.5, 193.0], [306.0, 243.3], [322.7, 240.9], [349.8, 227.5], [393.5, 188.0], [409.7, 176.4], [423.7, 184.8], [446.1, 171.1], [468.3, 172.4], [482.1, 178.4], [497.3, 190.5], [555.3, 260.6]
];

const SPA_CENTERLINE: [number, number][] = [
  [303.5, 100.3], [282.6, 63.8], [285.2, 60.0], [311.0, 72.1], [334.9, 89.5], [372.7, 134.0], [388.7, 146.0], [392.9, 153.7], [396.4, 170.7], [428.5, 225.7], [467.2, 362.2], [456.3, 377.4], [460.3, 397.6], [457.6, 406.3], [408.3, 439.9], [400.1, 437.4], [397.8, 432.4], [398.5, 427.1], [421.5, 410.8], [424.7, 406.6], [425.0, 401.0], [414.5, 368.0], [405.5, 318.8], [399.5, 310.4], [393.0, 307.1], [373.5, 306.2], [362.1, 311.3], [353.0, 323.6], [330.3, 378.9], [324.4, 383.4], [317.9, 384.5], [304.6, 378.4], [294.2, 379.2], [267.9, 416.0], [263.1, 417.8], [257.6, 416.4], [238.4, 402.4], [233.7, 394.6], [233.3, 384.2], [238.6, 369.9], [247.3, 355.9], [272.6, 331.5], [308.3, 312.6], [320.5, 303.1], [330.8, 287.7], [342.7, 260.5], [342.9, 247.4], [327.9, 208.1], [323.6, 183.7], [322.3, 157.0], [332.0, 155.5], [333.5, 152.6], [303.5, 100.3]
];

const INTERLAGOS_CENTERLINE: [number, number][] = [
  [253.3, 332.8], [276.8, 423.7], [286.7, 438.4], [298.3, 439.2], [316.1, 422.8], [322.8, 421.5], [352.3, 434.3], [376.2, 433.2], [396.4, 421.7], [408.9, 404.6], [421.6, 365.0], [469.3, 180.2], [469.6, 171.6], [466.3, 165.5], [457.5, 160.7], [422.3, 154.3], [405.6, 157.2], [395.7, 163.0], [380.0, 180.1], [314.7, 269.6], [302.8, 277.2], [283.2, 276.8], [264.5, 266.9], [258.4, 253.7], [251.9, 216.7], [253.5, 205.9], [259.5, 202.1], [268.2, 203.7], [279.8, 211.9], [287.7, 213.8], [298.9, 208.3], [302.8, 200.3], [302.5, 192.7], [297.4, 184.2], [273.0, 157.3], [266.2, 128.0], [269.8, 118.7], [279.4, 119.0], [311.7, 152.8], [327.2, 156.8], [344.1, 154.1], [358.7, 141.9], [393.0, 87.1], [391.9, 77.0], [383.3, 71.5], [348.9, 60.0], [315.0, 66.0], [279.2, 82.3], [264.8, 94.1], [257.8, 103.7], [244.3, 149.6], [231.0, 207.7], [230.0, 223.9], [231.7, 243.2], [253.3, 332.8]
];


const TRACKS: TrackDef[] = [
  {
    name: "Monaco",
    country: "Monte Carlo",
    flag: "🇲🇨",
    length: "3.337 km",
    accent: "#e11d48",
    halfWidth: 18,
    parTime: 32000,
    centerline: MONACO_CENTERLINE,
    aiLine: offsetLine(MONACO_CENTERLINE, 5, -3),
  },
  {
    name: "Silverstone",
    country: "United Kingdom",
    flag: "🇬🇧",
    length: "5.891 km",
    accent: "#2563eb",
    halfWidth: 22,
    parTime: 28000,
    centerline: SILVERSTONE_CENTERLINE,
    aiLine: offsetLine(SILVERSTONE_CENTERLINE, -4, 4),
  },
  {
    name: "Suzuka",
    country: "Japan",
    flag: "🇯🇵",
    length: "5.807 km",
    accent: "#dc2626",
    halfWidth: 20,
    parTime: 30000,
    centerline: SUZUKA_CENTERLINE,
    aiLine: offsetLine(SUZUKA_CENTERLINE, 4, 5),
  },
  {
    name: "Spa-Francorchamps",
    country: "Belgium",
    flag: "🇧🇪",
    length: "7.004 km",
    accent: "#f59e0b",
    halfWidth: 22,
    parTime: 35000,
    centerline: SPA_CENTERLINE,
    aiLine: offsetLine(SPA_CENTERLINE, -5, 3),
  },
  {
    name: "Interlagos",
    country: "Brazil",
    flag: "🇧🇷",
    length: "4.309 km",
    accent: "#16a34a",
    halfWidth: 20,
    parTime: 26000,
    centerline: INTERLAGOS_CENTERLINE,
    aiLine: offsetLine(INTERLAGOS_CENTERLINE, 3, -4),
  },
];

/* ═══════════════════════════════════════════════
   AI OPPONENTS
   ═══════════════════════════════════════════════ */

interface AIOpponent {
  name: string;
  color: string;
  emoji: string;
  /** Speed multiplier (1.0 = baseline, higher = faster) */
  speedFactor: number;
  /** Line offset from player's line (mimics different racing lines) */
  lineOffset: [number, number];
  /** Consistency (0-1, higher = less variation) */
  consistency: number;
}

const AI_OPPONENTS: AIOpponent[] = [
  { name: "Rusty", color: "#a855f7", emoji: "🟣", speedFactor: 0.82, lineOffset: [8, 8], consistency: 0.6 },
  { name: "Sunny", color: "#f59e0b", emoji: "🟡", speedFactor: 0.90, lineOffset: [-6, 5], consistency: 0.75 },
  { name: "Gio", color: "#06b6d4", emoji: "🔵", speedFactor: 0.95, lineOffset: [4, -7], consistency: 0.85 },
  { name: "Cy", color: "#ef4444", emoji: "🔴", speedFactor: 1.0, lineOffset: [-3, 4], consistency: 0.92 },
];

/* ═══════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════ */

function dist(a: { x: number; y: number } | [number, number], b: { x: number; y: number } | [number, number]) {
  const ax = Array.isArray(a) ? a[0] : a.x;
  const ay = Array.isArray(a) ? a[1] : a.y;
  const bx = Array.isArray(b) ? b[0] : b.x;
  const by = Array.isArray(b) ? b[1] : b.y;
  return Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
}

function totalLength(pts: { x: number; y: number }[] | [number, number][]) {
  let d = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    if (a && b) d += dist(a as any, b as any);
  }
  return d;
}

function formatTime(ms: number) {
  const totalSec = ms / 1000;
  const min = Math.floor(totalSec / 60);
  const sec = Math.floor(totalSec % 60);
  const cs = Math.floor((totalSec % 1) * 100);
  return `${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

function drawPath(ctx: CanvasRenderingContext2D, pts: [number, number][]) {
  pts.forEach(([x, y], i) => {
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
}

/** Finds indices along a centerline where the track curves sharply --
 * i.e. actual corners -- by measuring the turn angle at each point using
 * a fixed real-world lookback/lookahead distance (not a fixed index
 * offset, since this runs on the Catmull-Rom-smoothed centerline at
 * render time, whose point density is much higher than the raw data).
 * Replaces a manually-curated corner list: the geometry itself now
 * decides where curbs/gravel belong. */
function detectCorners(
  cl: [number, number][],
  angleThresholdDeg = 12,
  sampleDist = 14,
  minSpacing = 8
): number[] {
  const n = cl.length;
  if (n < 5) return [];

  const pointAtDistance = (fromIdx: number, dist: number, forward: boolean): [number, number] => {
    let acc = 0;
    let i = fromIdx;
    while (acc < dist) {
      const next = forward ? i + 1 : i - 1;
      if (next < 0 || next >= n) break;
      const cur = cl[i]!;
      const nxt = cl[next]!;
      acc += Math.hypot(nxt[0] - cur[0], nxt[1] - cur[1]);
      i = next;
    }
    return cl[i]!;
  };

  const found: number[] = [];
  for (let i = 2; i < n - 2; i++) {
    const pt = cl[i]!;
    const [x1, y1] = pt;
    const [xa, ya] = pointAtDistance(i, sampleDist, false);
    const [xb, yb] = pointAtDistance(i, sampleDist, true);
    const v1x = x1 - xa, v1y = y1 - ya;
    const v2x = xb - x1, v2y = yb - y1;
    const len1 = Math.hypot(v1x, v1y) || 1;
    const len2 = Math.hypot(v2x, v2y) || 1;
    const cos = (v1x * v2x + v1y * v2y) / (len1 * len2);
    const angleDeg = (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
    if (angleDeg > angleThresholdDeg) {
      if (found.length === 0 || i - (found[found.length - 1] ?? 0) >= minSpacing) {
        found.push(i);
      }
    }
  }
  return found;
}

/** Real F1-style kerbs: alternating red/white blocks at the OUTER edges of
 * the track surface at each detected corner, oriented along the direction
 * of travel there -- not a dashed line down the middle (which is what this
 * used to draw, mislabeled as "curbs"). */
function drawCurbs(
  ctx: CanvasRenderingContext2D,
  cl: [number, number][],
  cornerIndices: number[],
  hw: number
) {
  const blockLen = 14;
  const blocksPerSide = 5;
  for (const idx of cornerIndices) {
    const p0 = cl[Math.max(0, idx - 2)];
    const p1 = cl[idx];
    const p2 = cl[Math.min(cl.length - 1, idx + 2)];
    if (!p0 || !p1 || !p2) continue;

    const dx = p2[0] - p0[0];
    const dy = p2[1] - p0[1];
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const nx = -uy;
    const ny = ux;
    const angle = Math.atan2(uy, ux);

    for (const side of [1, -1]) {
      const edgeX = p1[0] + nx * hw * side;
      const edgeY = p1[1] + ny * hw * side;
      for (let b = 0; b < blocksPerSide; b++) {
        const offset = (b - (blocksPerSide - 1) / 2) * blockLen;
        const bx = edgeX + ux * offset;
        const by = edgeY + uy * offset;
        ctx.save();
        ctx.translate(bx, by);
        ctx.rotate(angle);
        ctx.fillStyle = b % 2 === 0 ? "#dc2626" : "#f5f5f5";
        ctx.fillRect(-blockLen / 2, -4, blockLen, 8);
        ctx.restore();
      }
    }
  }
}

/** Checkered start/finish line, perpendicular to the track direction at the
 * first centerline point. Every real circuit render needs one of these to
 * read as an actual track rather than a closed loop. */
function drawStartFinishLine(
  ctx: CanvasRenderingContext2D,
  cl: [number, number][],
  hw: number
) {
  const p0 = cl[0];
  const p1 = cl[1];
  if (!p0 || !p1) return;

  const dx = p1[0] - p0[0];
  const dy = p1[1] - p0[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const nx = -uy;
  const ny = ux;
  const angle = Math.atan2(uy, ux);

  const squares = 8;
  const sqSize = (hw * 2) / squares;
  for (let i = 0; i < squares; i++) {
    const t = -hw + i * sqSize + sqSize / 2;
    const cx = p0[0] + nx * t;
    const cy = p0[1] + ny * t;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.fillStyle = i % 2 === 0 ? "#111111" : "#ffffff";
    ctx.fillRect(-4, -sqSize / 2, 8, sqSize);
    ctx.restore();
  }
}

/** Smooth a centerline using Catmull-Rom → Bezier */
function smoothLine(pts: [number, number][], tension = 0.3): [number, number][] {
  if (pts.length < 3) return pts;
  const result: [number, number][] = [];
  for (let i = 0; i < pts.length; i++) {
    const p0 = pts[Math.max(0, i - 1)]!;
    const p1 = pts[i]!;
    const p2 = pts[Math.min(pts.length - 1, i + 1)]!;
    const p3 = pts[Math.min(pts.length - 1, i + 2)]!;
    // Subdivide each segment into 3 points
    for (let t = 0; t < 3; t++) {
      const f = t / 3;
      const tt = f * f;
      const ttt = tt * f;
      const x =
        0.5 *
        (2 * p1[0] +
          (-p0[0] + p2[0]) * f +
          (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * tt +
          (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * ttt);
      const y =
        0.5 *
        (2 * p1[1] +
          (-p0[1] + p2[1]) * f +
          (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * tt +
          (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * ttt);
      result.push([x, y]);
    }
  }
  return result;
}

/* ═══════════════════════════════════════════════
   LOCAL STORAGE SCORES
   ═══════════════════════════════════════════════ */

function loadScores(): Record<string, number> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem("dlr_scores") || "{}");
  } catch {
    return {};
  }
}

function saveScore(trackName: string, timeMs: number) {
  const scores = loadScores();
  const existing = scores[trackName];
  if (!existing || timeMs < existing) {
    scores[trackName] = timeMs;
    localStorage.setItem("dlr_scores", JSON.stringify(scores));
  }
}

function loadUserName(): string {
  if (typeof window === "undefined") return "Racer";
  return localStorage.getItem("dlr_username") || "Racer";
}

function saveUserName(name: string) {
  localStorage.setItem("dlr_username", name);
}

function loadGhostLine(trackName: string): { x: number; y: number }[] | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(localStorage.getItem(`dlr_ghost_${trackName}`) || "null");
  } catch {
    return null;
  }
}

function saveGhostLine(trackName: string, line: { x: number; y: number }[]) {
  localStorage.setItem(`dlr_ghost_${trackName}`, JSON.stringify(line));
}

/* ═══════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════ */

const RacingPage: NextPage = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [showModal, setShowModal] = useState(true);
  const [userName, setUserName] = useState("Racer");
  const [nameInput, setNameInput] = useState("");
  const [trackIdx, setTrackIdx] = useState(0);
  const [scores, setScores] = useState<Record<string, number>>({});
  const [ghostLine, setGhostLine] = useState<{ x: number; y: number }[] | null>(null);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [selectedAI, setSelectedAI] = useState(1); // Sunny default

  const track = TRACKS[trackIdx] as TrackDef;
  const smoothed = useRef<[number, number][][]>(TRACKS.map((t) => smoothLine(t.centerline)));
  const smoothedAI = useRef<[number, number][][]>(TRACKS.map((t) => smoothLine(t.aiLine || t.centerline)));

  // Game state
  const stateRef = useRef({
    drawing: false,
    line: [] as { x: number; y: number }[],
    racing: false,
    raceProgress: 0,
    startTime: 0,
    bestTime: null as number | null,
    laps: 0,
    avgSpeed: 0,
    // AI state
    aiProgress: 0,
    aiFinished: false,
    aiTime: null as number | null,
    // Result state
    showResult: false,
    resultTime: 0,
    resultAIName: "",
    resultAITime: 0,
    resultPosition: 0,
  });
  const animRef = useRef<number>(0);
  const [, forceUpdate] = useState(0);

  /* ─── Modal handlers ─── */
  const handleNameSubmit = () => {
    const name = nameInput.trim() || "Racer";
    setUserName(name);
    saveUserName(name);
  };

  const selectTrack = (idx: number) => {
    setTrackIdx(idx);
    setShowModal(false);
    stateRef.current.line = [];
    stateRef.current.bestTime = scores[TRACKS[idx]!.name] || null;
    stateRef.current.showResult = false;
    setGhostLine(loadGhostLine(TRACKS[idx]!.name));
    setTimeout(() => drawCanvas(), 100);
  };

  /* ─── Pointer events ─── */
  const getPos = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      const canvas = canvasRef.current!;
      const rect = canvas.getBoundingClientRect();
      const clientX = "touches" in e ? e.touches[0]!.clientX : e.clientX;
      const clientY = "touches" in e ? e.touches[0]!.clientY : e.clientY;
      return {
        x: ((clientX - rect.left) / rect.width) * canvas.width / (window.devicePixelRatio || 1),
        y: ((clientY - rect.top) / rect.height) * canvas.height / (window.devicePixelRatio || 1),
      };
    },
    []
  );

  const onPointerDown = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      const s = stateRef.current;
      if (s.racing || s.showResult) return;
      s.drawing = true;
      s.line = [getPos(e)];
    },
    [getPos]
  );

  const onPointerMove = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      const s = stateRef.current;
      if (!s.drawing || s.racing) return;
      const pos = getPos(e);
      const last = s.line[s.line.length - 1];
      if (last && dist(last, pos) > 3) {
        s.line.push(pos);
        drawCanvas();
      }
    },
    [getPos]
  );

  const onPointerUp = useCallback(() => {
    stateRef.current.drawing = false;
  }, []);

  /* ─── Canvas rendering ─── */
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || showModal) return;
    const ctx = canvas.getContext("2d")!;
    const s = stateRef.current;
    const W = 700;
    const H = 500;

    // ── Background: grass with subtle texture ──
    const grassGrad = ctx.createRadialGradient(W / 2, H / 2, 50, W / 2, H / 2, 450);
    grassGrad.addColorStop(0, "#1a7a3a");
    grassGrad.addColorStop(1, "#0f5c25");
    ctx.fillStyle = grassGrad;
    ctx.fillRect(0, 0, W, H);

    // Grass texture (subtle dots)
    ctx.fillStyle = "rgba(30, 140, 50, 0.3)";
    for (let i = 0; i < 200; i++) {
      const gx = (i * 137.5) % W;
      const gy = (i * 73.3) % H;
      ctx.beginPath();
      ctx.arc(gx, gy, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }

    const cl = smoothed.current[trackIdx]!;
    const hw = track.halfWidth;

    // ── Track surface — clean dark road like the reference ──
    // Road border (white edge lines)
    ctx.strokeStyle = "rgba(255,255,255,0.7)";
    ctx.lineWidth = hw * 2 + 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();

    // Asphalt fill
    ctx.strokeStyle = "#2d2d2d";
    ctx.lineWidth = hw * 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();

    // White dashed center line
    ctx.strokeStyle = "rgba(255,255,255,0.45)";
    ctx.lineWidth = 2;
    ctx.setLineDash([10, 12]);
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();
    ctx.setLineDash([]);

    // ── Start/finish line (checkered, perpendicular to track direction) ──
    drawStartFinishLine(ctx, cl, hw);

    // ── Checkpoint markers (circular dots at regular intervals) ──
    const numCheckpoints = Math.min(8, Math.floor(cl.length / 10));
    for (let c = 0; c < numCheckpoints; c++) {
      const ci = Math.floor((c / numCheckpoints) * (cl.length - 1));
      const pt = cl[ci]!;
      // Outer ring
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], 12, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.5)";
      ctx.lineWidth = 3;
      ctx.stroke();
      // Inner dot
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], 4, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.8)";
      ctx.fill();
    }

    // ── AI line (ghost) ──
    if (aiEnabled && s.racing) {
      const aiCl = smoothedAI.current[trackIdx]!;
      ctx.strokeStyle = AI_OPPONENTS[selectedAI]!.color;
      ctx.lineWidth = 3;
      ctx.globalAlpha = 0.3;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      aiCl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // ── Ghost line (dashed, visible before racing) ──
    if (ghostLine && ghostLine.length > 1 && !s.racing) {
      ctx.strokeStyle = "#a78bfa";
      ctx.lineWidth = 2;
      ctx.globalAlpha = 0.35;
      ctx.setLineDash([8, 6]);
      ctx.beginPath();
      ctx.moveTo(ghostLine[0]!.x, ghostLine[0]!.y);
      for (let i = 1; i < ghostLine.length; i++) ctx.lineTo(ghostLine[i]!.x, ghostLine[i]!.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // Ghost start dot
      ctx.fillStyle = "#a78bfa";
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(ghostLine[0]!.x, ghostLine[0]!.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // ── Player racing line ──
    if (s.line.length > 1) {
      // Glow
      ctx.shadowColor = "#22c55e";
      ctx.shadowBlur = 12;
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = 4;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(s.line[0]!.x, s.line[0]!.y);
      for (let i = 1; i < s.line.length; i++) ctx.lineTo(s.line[i]!.x, s.line[i]!.y);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Start dot
      ctx.fillStyle = "#22c55e";
      ctx.beginPath();
      ctx.arc(s.line[0]!.x, s.line[0]!.y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // ── Ghost car (previous best run) ──
    if (ghostLine && ghostLine.length > 1 && s.racing && s.line.length > 1) {
      const gIdx = Math.min(Math.floor(s.raceProgress * (ghostLine.length - 1)), ghostLine.length - 1);
      const gPos = ghostLine[gIdx]!;
      const gPrev = ghostLine[Math.max(0, gIdx - 8)]!;
      const gAngle = Math.atan2(gPos.y - gPrev.y, gPos.x - gPrev.x);

      // Ghost trail
      ctx.globalAlpha = 0.08;
      for (let i = 1; i <= 4; i++) {
        const ti = Math.max(0, gIdx - i * 6);
        const tp = ghostLine[ti]!;
        ctx.strokeStyle = "#a78bfa";
        ctx.lineWidth = 4 - i;
        ctx.beginPath();
        ctx.arc(tp.x, tp.y, 8 - i * 1.5, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // Ghost car body
      ctx.globalAlpha = 0.4;
      ctx.shadowColor = "#a78bfa";
      ctx.shadowBlur = 12;
      ctx.fillStyle = "#a78bfa";
      ctx.beginPath();
      ctx.arc(gPos.x, gPos.y, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // Ghost direction
      ctx.fillStyle = "#c4b5fd";
      ctx.beginPath();
      ctx.arc(gPos.x + Math.cos(gAngle) * 4, gPos.y + Math.sin(gAngle) * 4, 3, 0, Math.PI * 2);
      ctx.fill();

      // Ghost outline
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(gPos.x, gPos.y, 8, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;

      // Ghost name tag
      ctx.fillStyle = "#a78bfa";
      ctx.font = "bold 8px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.globalAlpha = 0.6;
      ctx.fillText("GHOST", gPos.x, gPos.y - 14);
      ctx.globalAlpha = 1;
    }

    // ── Player car ──
    if (s.racing && s.line.length > 1) {
      const idx = Math.min(Math.floor(s.raceProgress * (s.line.length - 1)), s.line.length - 1);
      const pos = s.line[idx]!;
      const prev = s.line[Math.max(0, idx - 8)]!;
      const angle = Math.atan2(pos.y - prev.y, pos.x - prev.x);

      // Speed trail
      ctx.globalAlpha = 0.2;
      for (let i = 1; i <= 5; i++) {
        const ti = Math.max(0, idx - i * 6);
        const tp = s.line[ti]!;
        ctx.strokeStyle = "#22c55e";
        ctx.lineWidth = 6 - i;
        ctx.beginPath();
        ctx.arc(tp.x, tp.y, 12 - i * 2, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // Car glow
      ctx.shadowColor = "#22c55e";
      ctx.shadowBlur = 20;
      ctx.fillStyle = "#22c55e";
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // Direction indicator
      ctx.fillStyle = "#bbf7d0";
      ctx.beginPath();
      ctx.arc(pos.x + Math.cos(angle) * 5, pos.y + Math.sin(angle) * 5, 4, 0, Math.PI * 2);
      ctx.fill();

      // Outline
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2);
      ctx.stroke();
    }

    // ── AI car ──
    if (aiEnabled && s.racing && s.line.length > 1) {
      const aiCl = smoothedAI.current[trackIdx]!;
      const aiIdx = Math.min(Math.floor(s.aiProgress * (aiCl.length - 1)), aiCl.length - 1);
      const aiPt = aiCl[aiIdx]!;
      const aiPrev = aiCl[Math.max(0, aiIdx - 8)]!;
      const aiColor = AI_OPPONENTS[selectedAI]!.color;

      // AI trail
      ctx.globalAlpha = 0.15;
      for (let i = 1; i <= 4; i++) {
        const ti = Math.max(0, aiIdx - i * 6);
        const tp = aiCl[ti]!;
        ctx.strokeStyle = aiColor;
        ctx.lineWidth = 5 - i;
        ctx.beginPath();
        ctx.arc(tp[0], tp[1], 10 - i * 2, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      // AI car glow
      ctx.shadowColor = aiColor;
      ctx.shadowBlur = 18;
      ctx.fillStyle = aiColor;
      ctx.beginPath();
      ctx.arc(aiPt[0], aiPt[1], 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // AI outline
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(aiPt[0], aiPt[1], 9, 0, Math.PI * 2);
      ctx.stroke();

      // AI name tag
      ctx.fillStyle = aiColor;
      ctx.font = "bold 9px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(AI_OPPONENTS[selectedAI]!.name, aiPt[0], aiPt[1] - 16);
    }

    // ── Track name overlay ──
    ctx.fillStyle = "rgba(0,0,0,0.65)";
    ctx.beginPath();
    ctx.roundRect(12, 12, 160, 32, 6);
    ctx.fill();
    ctx.fillStyle = track.accent;
    ctx.font = "bold 13px Inter, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(`${track.flag} ${track.name}`, 22, 34);

    // ── Line length overlay ──
    if (s.line.length > 1 && !s.racing && !s.showResult) {
      const len = totalLength(s.line);
      ctx.fillStyle = "rgba(0,0,0,0.65)";
      ctx.beginPath();
      ctx.roundRect(W - 135, 12, 123, 32, 6);
      ctx.fill();
      ctx.fillStyle = "#60a5fa";
      ctx.font = "bold 12px Inter, monospace";
      ctx.textAlign = "left";
      ctx.fillText(`${Math.round(len)}px  |  ${(len / (track.parTime / 50) * 100).toFixed(0)}%`, W - 125, 34);
    }

    // ── Result overlay ──
    if (s.showResult) {
      // Dim background
      ctx.fillStyle = "rgba(0,0,0,0.7)";
      ctx.fillRect(0, 0, W, H);

      // Result card
      const cardW = 400;
      const cardH = 260;
      const cardX = (W - cardW) / 2;
      const cardY = (H - cardH) / 2;

      ctx.fillStyle = "#1a1a2e";
      ctx.beginPath();
      ctx.roundRect(cardX, cardY, cardW, cardH, 16);
      ctx.fill();
      ctx.strokeStyle = s.resultPosition === 1 ? "#22c55e" : "#ef4444";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Position
      ctx.textAlign = "center";
      const posText = s.resultPosition === 1 ? "🏆 P1 — YOU WIN!" : `P${s.resultPosition} — ${s.resultAIName} wins`;
      ctx.fillStyle = s.resultPosition === 1 ? "#22c55e" : "#ef4444";
      ctx.font = "bold 22px Inter, sans-serif";
      ctx.fillText(posText, W / 2, cardY + 40);

      // Your time
      ctx.fillStyle = "#fff";
      ctx.font = "14px Inter, sans-serif";
      ctx.fillText("Your Time", W / 2, cardY + 75);
      ctx.font = "bold 28px monospace";
      ctx.fillStyle = "#22c55e";
      ctx.fillText(formatTime(s.resultTime), W / 2, cardY + 108);

      // AI time
      if (aiEnabled) {
        ctx.fillStyle = "#aaa";
        ctx.font = "14px Inter, sans-serif";
        ctx.fillText(`${AI_OPPONENTS[selectedAI]!.name}'s Time`, W / 2, cardY + 140);
        ctx.font = "bold 22px monospace";
        ctx.fillStyle = AI_OPPONENTS[selectedAI]!.color;
        ctx.fillText(formatTime(s.resultAITime), W / 2, cardY + 168);
      }

      // Gap
      const gap = s.resultTime - s.resultAITime;
      ctx.fillStyle = gap < 0 ? "#22c55e" : "#ef4444";
      ctx.font = "bold 14px Inter, sans-serif";
      ctx.fillText(
        gap < 0 ? `You were ${formatTime(-gap)} faster!` : `You were ${formatTime(gap)} slower`,
        W / 2,
        cardY + (aiEnabled ? 200 : 170)
      );

      // Close hint
      ctx.fillStyle = "#666";
      ctx.font = "12px Inter, sans-serif";
      ctx.fillText("Click anywhere to continue", W / 2, cardY + cardH - 15);
    }
  }, [trackIdx, showModal, aiEnabled, selectedAI, track]);

  /* ─── Race animation ─── */
  const animate = useCallback(() => {
    const s = stateRef.current;
    if (!s.racing) return;

    const lineLen = s.line.length;
    const aiCl = smoothedAI.current[trackIdx]!;
    const aiOpp = AI_OPPONENTS[selectedAI]!;

    // Player speed (variable based on line curvature)
    const pIdx = Math.floor(s.raceProgress * (lineLen - 1));
    const pAhead = Math.min(pIdx + 10, lineLen - 1);
    const pBehind = Math.max(pIdx - 10, 0);
    const pSegLen = dist(s.line[pBehind]!, s.line[pAhead]!);
    const pSpeed = Math.max(0.3, Math.min(1.2, pSegLen / 80));
    s.raceProgress += 0.005 * pSpeed;

    // AI speed (with slight randomness for consistency)
    const aIdx = Math.floor(s.aiProgress * (aiCl.length - 1));
    const aAhead = Math.min(aIdx + 10, aiCl.length - 1);
    const aBehind = Math.max(aIdx - 10, 0);
    const aSegLen = dist(aiCl[aBehind]!, aiCl[aAhead]!);
    const aBaseSpeed = Math.max(0.3, Math.min(1.2, aSegLen / 80));
    const jitter = (1 - aiOpp.consistency) * 0.15 * Math.sin(Date.now() / 200);
    s.aiProgress += 0.005 * aBaseSpeed * aiOpp.speedFactor * (1 + jitter);

    // Update timer
    forceUpdate((n) => n + 1);

    // Check finish
    const playerDone = s.raceProgress >= 1;
    const aiDone = s.aiProgress >= 1;

    if (playerDone || aiDone) {
      s.racing = false;
      const playerTime = Date.now() - s.startTime;
      s.resultTime = playerTime;

      if (aiDone && !s.aiFinished) {
        s.aiFinished = true;
        s.aiTime = playerTime / aiOpp.speedFactor; // AI finishes relative to its speed
      }

      // If player finished, compute AI time
      if (playerDone) {
        s.resultAITime = s.aiTime || Math.round(playerTime / aiOpp.speedFactor);
        s.resultPosition = playerTime < s.resultAITime ? 1 : 2;
        s.resultAIName = aiOpp.name;
        s.showResult = true;

        // Save score and ghost line
        if (s.resultPosition === 1) {
          saveScore(track.name, playerTime);
          saveGhostLine(track.name, s.line);
          setScores(loadScores());
        }
        // Update best time
        if (!s.bestTime || playerTime < s.bestTime) {
          s.bestTime = playerTime;
        }
        s.laps++;
      }

      cancelAnimationFrame(animRef.current);
      drawCanvas();
      forceUpdate((n) => n + 1);
      return;
    }

    drawCanvas();
    animRef.current = requestAnimationFrame(animate);
  }, [trackIdx, selectedAI, drawCanvas]);

  /* ─── Button handlers ─── */
  const startRace = () => {
    const s = stateRef.current;
    if (s.line.length < 15) {
      alert("Draw a longer racing line first!");
      return;
    }
    s.racing = true;
    s.raceProgress = 0;
    s.aiProgress = 0;
    s.aiFinished = false;
    s.aiTime = null;
    s.startTime = Date.now();
    s.showResult = false;
    forceUpdate((n) => n + 1);
    animRef.current = requestAnimationFrame(animate);
  };

  const clearLine = () => {
    const s = stateRef.current;
    s.line = [];
    s.racing = false;
    s.raceProgress = 0;
    s.bestTime = scores[track.name] || null;
    s.showResult = false;
    cancelAnimationFrame(animRef.current);
    drawCanvas();
    forceUpdate((n) => n + 1);
  };

  const handleCanvasClick = () => {
    if (stateRef.current.showResult) {
      stateRef.current.showResult = false;
      drawCanvas();
      forceUpdate((n) => n + 1);
    }
  };

  /* ─── Init ─── */
  useEffect(() => {
    setScores(loadScores());
    const savedName = loadUserName();
    setUserName(savedName);
    setNameInput(savedName);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || showModal) return;
    const resize = () => {
      const parent = canvas.parentElement;
      const w = parent?.offsetWidth || 700;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = 700 * dpr;
      canvas.height = 500 * dpr;
      canvas.style.width = "100%";
      canvas.style.height = "auto";
      canvas.style.aspectRatio = "700 / 500";
      const ctx = canvas.getContext("2d")!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawCanvas();
    };
    const t = setTimeout(resize, 50);
    window.addEventListener("resize", resize);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animRef.current);
    };
  }, [drawCanvas, showModal]);

  useEffect(() => {
    if (!showModal) drawCanvas();
  }, [trackIdx, showModal, drawCanvas]);

  const s = stateRef.current;
  const elapsed = s.racing ? Date.now() - s.startTime : 0;
  const lineLen = s.line.length > 1 ? Math.round(totalLength(s.line)) : 0;

  /* ═══════════════════════════════════════════════
     WELCOME MODAL
     ═══════════════════════════════════════════════ */
  if (showModal) {
    return (
      <>
        <Head>
          <title>Draw Line Racing - F1 Race Predictor</title>
        </Head>
        <div className="min-h-screen bg-[#0c0f1a] text-white flex flex-col">
          {/* Header */}
          <header className="bg-black/40 backdrop-blur-lg border-b border-white/5 px-4 py-3">
            <div className="max-w-5xl mx-auto flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2 text-zinc-400 hover:text-white transition group">
                <svg className="w-5 h-5 group-hover:-translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                <span className="font-medium">Race Predictor</span>
              </Link>
              <div className="flex items-center gap-3">
                <h1 className="text-lg font-bold">
                  <span className="bg-gradient-to-r from-green-400 to-emerald-500 bg-clip-text text-transparent">🏎️ Draw Line Racing</span>
                </h1>
                <button
                  onClick={() => {
                    if (!document.fullscreenElement) document.documentElement.requestFullscreen();
                    else document.exitFullscreen();
                  }}
                  className="bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-full text-xs font-bold shadow-lg flex items-center gap-1.5 transition"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
                  Fullscreen
                </button>
              </div>
            </div>
          </header>

          <main className="flex-1 flex items-center justify-center p-4">
            <div className="max-w-4xl w-full">
              {/* Greeting */}
              <div className="text-center mb-8">
                <h2 className="text-4xl font-bold mb-2">
                  Welcome back, <span className="text-green-400">{userName}</span>! 👋
                </h2>
                <p className="text-zinc-400 text-lg">Select a track to start racing</p>
              </div>

              {/* Name input */}
              <div className="flex justify-center mb-8">
                <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-xl px-4 py-2">
                  <span className="text-zinc-500 text-sm">Name:</span>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    onBlur={handleNameSubmit}
                    onKeyDown={(e) => e.key === "Enter" && handleNameSubmit()}
                    className="bg-transparent text-white font-semibold outline-none w-40"
                    placeholder="Your name..."
                  />
                </div>
              </div>

              {/* AI toggle */}
              <div className="flex justify-center mb-8">
                <button
                  onClick={() => setAiEnabled(!aiEnabled)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-xl border transition ${
                    aiEnabled
                      ? "bg-green-500/10 border-green-500/30 text-green-400"
                      : "bg-white/5 border-white/10 text-zinc-500"
                  }`}
                >
                  <div className={`w-2 h-2 rounded-full ${aiEnabled ? "bg-green-400" : "bg-zinc-600"}`} />
                  {aiEnabled ? "AI Opponents ON" : "AI Opponents OFF"}
                </button>
              </div>

              {/* Track grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {TRACKS.map((t, i) => {
                  const bestTime = scores[t.name];
                  return (
                    <button
                      key={t.name}
                      onClick={() => selectTrack(i)}
                      className="group relative bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 rounded-2xl p-4 transition-all hover:scale-[1.03] active:scale-[0.98]"
                    >
                      {/* Track visual with animated racing dot */}
                      <div className="aspect-square mb-3 flex items-center justify-center">
                        <svg viewBox="0 0 200 150" className="w-full h-full opacity-40 group-hover:opacity-70 transition">
                          <polyline
                            points={t.centerline.map(([x, y]) => `${x * 0.28 + 20},${y * 0.24 + 10}`).join(" ")}
                            fill="none"
                            stroke={t.accent}
                            strokeWidth="3"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          {/* Animated racing dot */}
                          <circle r="4" fill="#22c55e" opacity="0.9">
                            <animateMotion
                              dur={`${3 + i * 0.5}s`}
                              repeatCount="indefinite"
                              path={t.centerline.map(([x, y], idx) => `${idx === 0 ? 'M' : 'L'}${x * 0.28 + 20},${y * 0.24 + 10}`).join(' ')}
                            />
                          </circle>
                          {/* Dot glow */}
                          <circle r="7" fill="#22c55e" opacity="0.2">
                            <animateMotion
                              dur={`${3 + i * 0.5}s`}
                              repeatCount="indefinite"
                              path={t.centerline.map(([x, y], idx) => `${idx === 0 ? 'M' : 'L'}${x * 0.28 + 20},${y * 0.24 + 10}`).join(' ')}
                            />
                          </circle>
                        </svg>
                      </div>
                      {/* Info */}
                      <div className="text-center">
                        <div className="text-lg mb-1">{t.flag}</div>
                        <div className="font-bold text-sm group-hover:text-white transition">{t.name}</div>
                        <div className="text-xs text-zinc-500">{t.length}</div>
                        {bestTime && (
                          <div className="text-xs text-yellow-400 mt-1 font-mono">Best: {formatTime(bestTime)}</div>
                        )}
                      </div>
                      {/* Play badge */}
                      <div className="absolute top-3 right-3 bg-green-500 text-white text-xs font-bold px-2 py-1 rounded-full opacity-0 group-hover:opacity-100 transition">
                        Play
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </main>
        </div>
      </>
    );
  }

  /* ═══════════════════════════════════════════════
     GAME VIEW
     ═══════════════════════════════════════════════ */
  return (
    <>
      <Head>
        <title>{track.name} - Draw Line Racing</title>
      </Head>
      <div className="min-h-screen bg-[#0c0f1a] text-white">
        {/* Header */}
        <header className="sticky top-0 z-50 bg-black/40 backdrop-blur-lg border-b border-white/5">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <button
              onClick={() => { setShowModal(true); clearLine(); }}
              className="flex items-center gap-2 text-zinc-400 hover:text-white transition group"
            >
              <svg className="w-5 h-5 group-hover:-translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              <span className="font-medium">Change Track</span>
            </button>              <div className="flex items-center gap-3">
              <div className="hidden sm:flex items-center gap-2 bg-white/5 px-3 py-1.5 rounded-full border border-white/10">
                <div className={`w-2 h-2 rounded-full ${s.racing ? "bg-red-500 animate-pulse" : "bg-green-400"}`} />
                <span className="text-sm text-zinc-300">
                  {s.racing ? "Racing..." : s.line.length > 0 ? "Ready to race" : "Draw your line"}
                </span>
              </div>
              <button
                onClick={() => {
                  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
                  else document.exitFullscreen();
                }}
                className="bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-full text-xs font-bold shadow-lg flex items-center gap-1.5 transition"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
                Fullscreen
              </button>
              <h1 className="text-lg font-bold">
                <span style={{ color: track.accent }}>🏎️</span>{" "}
                <span className="bg-gradient-to-r from-green-400 to-emerald-500 bg-clip-text text-transparent">Draw Line Racing</span>
              </h1>
            </div>
          </div>
        </header>

        <main className="max-w-7xl mx-auto p-4 sm:p-6">
          <div className="grid lg:grid-cols-[1fr_280px] gap-6">
            {/* Left */}
            <div className="space-y-4">
              {/* Canvas */}
              <div className="relative rounded-2xl border border-zinc-800 overflow-hidden shadow-2xl bg-[#0a0d16]">
                <canvas
                  ref={canvasRef}
                  className="w-full cursor-crosshair"
                  style={{ aspectRatio: "700 / 500" }}
                  onMouseDown={onPointerDown}
                  onMouseMove={onPointerMove}
                  onMouseUp={onPointerUp}
                  onMouseLeave={onPointerUp}
                  onTouchStart={onPointerDown}
                  onTouchMove={onPointerMove}
                  onTouchEnd={onPointerUp}
                  onClick={handleCanvasClick}
                />
                {s.drawing && (
                  <div className="absolute bottom-3 left-3 z-10">
                    <div className="flex items-center gap-2 bg-green-500/90 px-3 py-1.5 rounded-full">
                      <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                      <span className="text-xs font-bold text-white">DRAWING</span>
                    </div>
                  </div>
                )}
                <div className="absolute bottom-3 right-3 z-10 bg-black/60 backdrop-blur-sm px-3 py-1.5 rounded-full">
                  <span className="text-xs text-zinc-400">{track.length} · {track.country}</span>
                </div>
              </div>

              {/* Controls */}
              <div className="flex flex-wrap gap-3">
                <button onClick={clearLine} className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-5 py-3 bg-zinc-800 hover:bg-zinc-700 rounded-xl font-semibold transition-all border border-zinc-700">
                  Clear
                </button>
                <button onClick={startRace} disabled={s.racing} className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-8 py-3 bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 rounded-xl font-bold transition-all shadow-lg shadow-green-500/20 disabled:opacity-50 disabled:cursor-not-allowed">
                  {s.racing ? "Racing..." : "🏁 Start Race"}
                </button>
                {/* AI opponent selector */}
                {aiEnabled && (
                  <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-xl px-3">
                    <span className="text-xs text-zinc-500">vs</span>
                    {AI_OPPONENTS.map((ai, i) => (
                      <button
                        key={ai.name}
                        onClick={() => setSelectedAI(i)}
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm transition-all ${
                          i === selectedAI ? "ring-2 ring-offset-1 ring-offset-[#0c0f1a] scale-110" : "opacity-50 hover:opacity-80"
                        }`}
                        style={{ backgroundColor: ai.color + "30" }}
                        title={ai.name}
                      >
                        {ai.emoji}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <p className="text-xs text-zinc-500">
                Draw a racing line on the circuit, then hit Start Race. Shorter, smoother lines = faster times!
              </p>
            </div>

            {/* Right - Stats */}
            <div className="space-y-4">
              <div className="bg-zinc-900/50 rounded-2xl border border-zinc-800 p-5 text-center">
                <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">Lap Time</div>
                <div className="text-5xl font-bold font-mono text-white tabular-nums">{formatTime(elapsed)}</div>
              </div>

              <div className="bg-gradient-to-br from-yellow-500/10 to-amber-500/5 rounded-2xl border border-yellow-500/15 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-yellow-500/15 flex items-center justify-center text-2xl">⭐</div>
                  <div>
                    <div className="text-xs font-semibold text-yellow-500/60 uppercase tracking-wider">Best Time</div>
                    <div className="text-2xl font-bold font-mono text-yellow-400">
                      {s.bestTime !== null ? formatTime(s.bestTime) : "--:--.--"}
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-zinc-900/50 rounded-2xl border border-zinc-800 p-4 space-y-3">
                <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Race Stats</h3>
                {[
                  { label: "Line Length", value: `${lineLen}px`, icon: "📏" },
                  { label: "Laps", value: String(s.laps), icon: "🔄" },
                  { label: "Opponent", value: aiEnabled ? AI_OPPONENTS[selectedAI]!.name : "None", icon: "🤖" },
                  { label: "Ghost", value: ghostLine ? "Active" : "None", icon: "👻" },
                ].map((item) => (
                  <div key={item.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-sm text-zinc-400">
                      <span>{item.icon}</span> {item.label}
                    </span>
                    <span className="font-mono font-bold text-white">{item.value}</span>
                  </div>
                ))}
              </div>

              {/* All-time best scores */}
              <div className="bg-zinc-900/50 rounded-2xl border border-zinc-800 p-4">
                <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Best Times</h3>
                {TRACKS.map((t) => (
                  <div key={t.name} className={`flex items-center justify-between py-1.5 ${t.name === track.name ? "text-white" : "text-zinc-500"}`}>
                    <span className="text-sm flex items-center gap-1">
                      <span>{t.flag}</span> {t.name}
                    </span>
                    <span className="font-mono text-sm">{scores[t.name] ? formatTime(scores[t.name]!) : "--:--"}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
};

export default RacingPage;
