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
  centerline: [number, number][];
  halfWidth: number;
  corners: { label: string; at: number }[];
  parTime: number;
  aiLine?: [number, number][];
}

function offsetLine(pts: [number, number][], dx: number, dy: number): [number, number][] {
  return pts.map(([x, y]) => [x + dx, y + dy]);
}

// ─── MONACO ───
const MONACO_CENTERLINE: [number, number][] = [
  [100, 390], [150, 380], [200, 370], [250, 360],
  [280, 345], [295, 325], [290, 305],
  [270, 275], [250, 245], [235, 215], [225, 185],
  [225, 155], [240, 130], [265, 115],
  [295, 108], [325, 115], [345, 135],
  [355, 160], [360, 190], [355, 220],
  [345, 250], [325, 268], [300, 272], [280, 260],
  [275, 240], [285, 220],
  [305, 205], [335, 195], [370, 190],
  [410, 185], [450, 185], [490, 190],
  [515, 200], [525, 215], [520, 230], [510, 225],
  [500, 210], [495, 190], [500, 170],
  [510, 155], [525, 145], [540, 150], [545, 165],
  [540, 180], [525, 190], [515, 185],
  [510, 195], [505, 215], [495, 230],
  [475, 245], [450, 255], [420, 265],
  [385, 285], [350, 310], [310, 340],
  [265, 360], [220, 372], [175, 380], [130, 386], [100, 390],
];

// ─── SILVERSTONE ───
const SILVERSTONE_CENTERLINE: [number, number][] = [
  [155, 370], [175, 355], [185, 335],
  [180, 315], [165, 300], [150, 290],
  [140, 275], [135, 255],
  [140, 225], [150, 195], [165, 165],
  [190, 140], [225, 120], [265, 108],
  [305, 100], [335, 98], [355, 108],
  [370, 125], [380, 145], [385, 165],
  [395, 180], [415, 185],
  [450, 180], [490, 170], [530, 165],
  [565, 165], [590, 178], [600, 200],
  [595, 225], [578, 245], [555, 258],
  [530, 265], [505, 268],
  [470, 275], [430, 285], [390, 295],
  [350, 305], [315, 315], [285, 325],
  [255, 340], [225, 355], [195, 365], [155, 370],
];

// ─── SUZUKA ───
const SUZUKA_CENTERLINE: [number, number][] = [
  [530, 400], [520, 365], [500, 325], [480, 290], [455, 260],
  [425, 238],
  [400, 225], [378, 215], [362, 208],
  [352, 200],
  [340, 190], [322, 178],
  [300, 170],
  [278, 165], [258, 160], [240, 152],
  [222, 148],
  [206, 158], [196, 175], [190, 195], [188, 213],
  [196, 228],
  [212, 236], [230, 233], [248, 220],
  [263, 204],
  [280, 192],
  [300, 183],
  [320, 178], [338, 178], [352, 184], [360, 193],
  [352, 200],
  [368, 196], [400, 206], [438, 216],
  [478, 224],
  [505, 222],
  [528, 208], [538, 188],
  [536, 168],
  [520, 158], [505, 162], [498, 178], [500, 200],
  [510, 240], [518, 285], [524, 330], [528, 368], [530, 400],
];

// ─── SPA ───
const SPA_CENTERLINE: [number, number][] = [
  [110, 100], [130, 115], [140, 138], [135, 160],
  [125, 185], [118, 210], [115, 235],
  [118, 260], [130, 278], [148, 288],
  [172, 290], [198, 280], [225, 265], [250, 245],
  [285, 220], [325, 198], [368, 180], [415, 168],
  [455, 162], [485, 165], [505, 178],
  [510, 198], [500, 215], [485, 228],
  [475, 248], [468, 272], [455, 295],
  [438, 312], [418, 322],
  [395, 328], [368, 330], [342, 328],
  [318, 322], [298, 312],
  [282, 298], [272, 278], [268, 258],
  [275, 242], [290, 232],
  [312, 228], [338, 230], [365, 238],
  [392, 252], [415, 270],
  [435, 290], [448, 315], [455, 342],
  [455, 368], [448, 390],
  [435, 405], [418, 412], [400, 408],
  [390, 395], [395, 378],
  [395, 355], [388, 328], [375, 298],
  [355, 265], [330, 235], [300, 210],
  [265, 190], [228, 172], [192, 155],
  [158, 138], [130, 118], [110, 100],
];

// ─── INTERLAGOS ───
const INTERLAGOS_CENTERLINE: [number, number][] = [
  [540, 100], [535, 135], [528, 170], [518, 205],
  [505, 235], [488, 258], [465, 272],
  [440, 278], [418, 270], [402, 255],
  [385, 238], [365, 228], [342, 225],
  [318, 230], [298, 242], [285, 260],
  [280, 282], [285, 302],
  [295, 318], [308, 330], [325, 335],
  [342, 332], [355, 320], [360, 305],
  [358, 288], [348, 272], [335, 262],
  [320, 258], [308, 265], [298, 278],
  [295, 298], [298, 320], [308, 340],
  [325, 355], [348, 365], [375, 370],
  [405, 370], [435, 362], [462, 348],
  [485, 328], [502, 305], [515, 278],
  [525, 248], [532, 215],
  [538, 180], [540, 145], [540, 100],
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
    corners: [
      { label: "Ste Dévote", at: 5 },
      { label: "Casino", at: 10 },
      { label: "Hairpin", at: 16 },
      { label: "Tunnel", at: 22 },
      { label: "Chicane", at: 25 },
      { label: "Pool", at: 32 },
      { label: "Rascasse", at: 37 },
    ],
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
    corners: [
      { label: "Copse", at: 8 },
      { label: "Maggots", at: 11 },
      { label: "Becketts", at: 14 },
      { label: "Stowe", at: 20 },
      { label: "Vale", at: 23 },
      { label: "Club", at: 25 },
      { label: "Abbey", at: 30 },
    ],
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
    corners: [
      { label: "T1", at: 5 },
      { label: "S Curves", at: 9 },
      { label: "Degner", at: 16 },
      { label: "Hairpin", at: 21 },
      { label: "Spoon", at: 27 },
      { label: "130R", at: 33 },
      { label: "Casio", at: 36 },
    ],
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
    corners: [
      { label: "La Source", at: 1 },
      { label: "Eau Rouge", at: 7 },
      { label: "Raidillon", at: 10 },
      { label: "Les Combes", at: 15 },
      { label: "Pouhon", at: 23 },
      { label: "Blanchimont", at: 34 },
      { label: "Bus Stop", at: 38 },
    ],
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
    corners: [
      { label: "Senna S", at: 6 },
      { label: "Ferradura", at: 12 },
      { label: "Pinheirinho", at: 18 },
      { label: "Bico de Pato", at: 21 },
      { label: "Junção", at: 25 },
      { label: "Curva 1", at: 35 },
    ],
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
  speedFactor: number;
  lineOffset: [number, number];
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

/** Real F1-style kerbs: alternating red/white blocks at the OUTER edges of
 * the track surface at each named corner, oriented along the direction of
 * travel there. */
function drawCurbs(
  ctx: CanvasRenderingContext2D,
  cl: [number, number][],
  corners: { label: string; at: number }[],
  hw: number
) {
  const blockLen = 14;
  const blocksPerSide = 5;
  for (const c of corners) {
    const idx = Math.min(c.at * 3, cl.length - 1);
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
 * first centerline point. */
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
  const [selectedAI, setSelectedAI] = useState(1);

  const track = TRACKS[trackIdx] as TrackDef;
  const smoothed = useRef<[number, number][][]>(TRACKS.map((t) => smoothLine(t.centerline)));
  const smoothedAI = useRef<[number, number][][]>(TRACKS.map((t) => smoothLine(t.aiLine || t.centerline)));

  const stateRef = useRef({
    drawing: false,
    line: [] as { x: number; y: number }[],
    racing: false,
    raceProgress: 0,
    startTime: 0,
    bestTime: null as number | null,
    laps: 0,
    avgSpeed: 0,
    aiProgress: 0,
    aiFinished: false,
    aiTime: null as number | null,
    showResult: false,
    resultTime: 0,
    resultAIName: "",
    resultAITime: 0,
    resultPosition: 0,
  });
  const animRef = useRef<number>(0);
  const [, forceUpdate] = useState(0);

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

    // Grass texture
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

    // ── Runoff areas (gravel traps at key corners) ──
    ctx.fillStyle = "#c4a55a";
    ctx.globalAlpha = 0.3;
    for (const c of track.corners) {
      const idx = Math.min(c.at * 3, cl.length - 1);
      const pt = cl[idx];
      if (pt) {
        ctx.beginPath();
        ctx.arc(pt[0] + 25, pt[1] + 25, 20, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // ── Track surface ──
    ctx.strokeStyle = "#3a3a3a";
    ctx.lineWidth = hw * 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();

    // Asphalt texture
    ctx.strokeStyle = "#404040";
    ctx.lineWidth = hw * 1.8;
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();
    ctx.setLineDash([]);

    // ── Track edges ──
    ctx.strokeStyle = "#666";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    cl.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    ctx.stroke();

    // ── Curb strips (real kerbs: red/white blocks at the track EDGES) ──
    drawCurbs(ctx, cl, track.corners, hw);

    // ── Start/finish line (checkered, perpendicular to track direction) ──
    drawStartFinishLine(ctx, cl, hw);

    // ── Corner labels ──
    ctx.font = "bold 9px Inter, sans-serif";
    ctx.textAlign = "center";
    for (const c of track.corners) {
      const idx = Math.min(c.at * 3, cl.length - 1);
      const pt = cl[idx];
      if (pt) {
        const tw = ctx.measureText(c.label).width;
        ctx.fillStyle = "rgba(0,0,0,0.7)";
        ctx.beginPath();
        ctx.roundRect(pt[0] - tw / 2 - 4, pt[1] - hw - 18, tw + 8, 14, 3);
        ctx.fill();
        ctx.fillStyle = track.accent;
        ctx.fillText(c.label, pt[0], pt[1] - hw - 8);
      }
    }

    // ── Pit lane indicator ──
    ctx.fillStyle = "rgba(255,255,255,0.15)";
    ctx.font = "bold 10px Inter, sans-serif";
    ctx.fillText("PIT", cl[0]![0] + 30, cl[0]![1] - hw - 4);

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

      ctx.fillStyle = "#a78bfa";
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(ghostLine[0]!.x, ghostLine[0]!.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // ── Player racing line ──
    if (s.line.length > 1) {
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

      ctx.globalAlpha = 0.4;
      ctx.shadowColor = "#a78bfa";
      ctx.shadowBlur = 12;
      ctx.fillStyle = "#a78bfa";
      ctx.beginPath();
      ctx.arc(gPos.x, gPos.y, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.fillStyle = "#c4b5fd";
      ctx.beginPath();
      ctx.arc(gPos.x + Math.cos(gAngle) * 4, gPos.y + Math.sin(gAngle) * 4, 3, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(gPos.x, gPos.y, 8, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;

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

      ctx.shadowColor = "#22c55e";
      ctx.shadowBlur = 20;
      ctx.fillStyle = "#22c55e";
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 10, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.fillStyle = "#bbf7d0";
      ctx.beginPath();
      ctx.arc(pos.x + Math.cos(angle) * 5, pos.y + Math.sin(angle) * 5, 4, 0, Math.PI * 2);
      ctx.fill();

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
      const aiColor = AI_OPPONENTS[selectedAI]!.color;

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

      ctx.shadowColor = aiColor;
      ctx.shadowBlur = 18;
      ctx.fillStyle = aiColor;
      ctx.beginPath();
      ctx.arc(aiPt[0], aiPt[1], 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(aiPt[0], aiPt[1], 9, 0, Math.PI * 2);
      ctx.stroke();

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
      ctx.fillStyle = "rgba(0,0,0,0.7)";
      ctx.fillRect(0, 0, W, H);

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

      ctx.textAlign = "center";
      const posText = s.resultPosition === 1 ? "🏆 P1 — YOU WIN!" : `P${s.resultPosition} — ${s.resultAIName} wins`;
      ctx.fillStyle = s.resultPosition === 1 ? "#22c55e" : "#ef4444";
      ctx.font = "bold 22px Inter, sans-serif";
      ctx.fillText(posText, W / 2, cardY + 40);

      ctx.fillStyle = "#fff";
      ctx.font = "14px Inter, sans-serif";
      ctx.fillText("Your Time", W / 2, cardY + 75);
      ctx.font = "bold 28px monospace";
      ctx.fillStyle = "#22c55e";
      ctx.fillText(formatTime(s.resultTime), W / 2, cardY + 108);

      if (aiEnabled) {
        ctx.fillStyle = "#aaa";
        ctx.font = "14px Inter, sans-serif";
        ctx.fillText(`${AI_OPPONENTS[selectedAI]!.name}'s Time`, W / 2, cardY + 140);
        ctx.font = "bold 22px monospace";
        ctx.fillStyle = AI_OPPONENTS[selectedAI]!.color;
        ctx.fillText(formatTime(s.resultAITime), W / 2, cardY + 168);
      }

      const gap = s.resultTime - s.resultAITime;
      ctx.fillStyle = gap < 0 ? "#22c55e" : "#ef4444";
      ctx.font = "bold 14px Inter, sans-serif";
      ctx.fillText(
        gap < 0 ? `You were ${formatTime(-gap)} faster!` : `You were ${formatTime(gap)} slower`,
        W / 2,
        cardY + (aiEnabled ? 200 : 170)
      );

      ctx.fillStyle = "#666";
      ctx.font = "12px Inter, sans-serif";
      ctx.fillText("Click anywhere to continue", W / 2, cardY + cardH - 15);
    }
  }, [trackIdx, showModal, aiEnabled, selectedAI, track, ghostLine]);

  /* ─── Race animation ─── */
  const animate = useCallback(() => {
    const s = stateRef.current;
    if (!s.racing) return;

    const lineLen = s.line.length;
    const aiCl = smoothedAI.current[trackIdx]!;
    const aiOpp = AI_OPPONENTS[selectedAI]!;

    const pIdx = Math.floor(s.raceProgress * (lineLen - 1));
    const pAhead = Math.min(pIdx + 10, lineLen - 1);
    const pBehind = Math.max(pIdx - 10, 0);
    const pSegLen = dist(s.line[pBehind]!, s.line[pAhead]!);
    const pSpeed = Math.max(0.3, Math.min(1.2, pSegLen / 80));
    s.raceProgress += 0.005 * pSpeed;

    const aIdx = Math.floor(s.aiProgress * (aiCl.length - 1));
    const aAhead = Math.min(aIdx + 10, aiCl.length - 1);
    const aBehind = Math.max(aIdx - 10, 0);
    const aSegLen = dist(aiCl[aBehind]!, aiCl[aAhead]!);
    const aBaseSpeed = Math.max(0.3, Math.min(1.2, aSegLen / 80));
    const jitter = (1 - aiOpp.consistency) * 0.15 * Math.sin(Date.now() / 200);
    s.aiProgress += 0.005 * aBaseSpeed * aiOpp.speedFactor * (1 + jitter);

    forceUpdate((n) => n + 1);

    const playerDone = s.raceProgress >= 1;
    const aiDone = s.aiProgress >= 1;

    if (playerDone || aiDone) {
      s.racing = false;
      const playerTime = Date.now() - s.startTime;
      s.resultTime = playerTime;

      if (aiDone && !s.aiFinished) {
        s.aiFinished = true;
        s.aiTime = playerTime / aiOpp.speedFactor;
      }

      if (playerDone) {
        s.resultAITime = s.aiTime || Math.round(playerTime / aiOpp.speedFactor);
        s.resultPosition = playerTime < s.resultAITime ? 1 : 2;
        s.resultAIName = aiOpp.name;
        s.showResult = true;

        if (s.resultPosition === 1) {
          saveScore(track.name, playerTime);
          saveGhostLine(track.name, s.line);
          setScores(loadScores());
        }
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
  }, [trackIdx, selectedAI, drawCanvas, track]);

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
          <header className="bg-black/40 backdrop-blur-lg border-b border-white/5 px-4 py-3">
            <div className="max-w-5xl mx-auto flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2 text-zinc-400 hover:text-white transition group">
                <svg className="w-5 h-5 group-hover:-translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                <span className="font-medium">Race Predictor</span>
              </Link>
              <h1 className="text-lg font-bold">
                <span className="bg-gradient-to-r from-green-400 to-emerald-500 bg-clip-text text-transparent">🏎️ Draw Line Racing</span>
              </h1>
            </div>
          </header>

          <main className="flex-1 flex items-center justify-center p-4">
            <div className="max-w-4xl w-full">
              <div className="text-center mb-8">
                <h2 className="text-4xl font-bold mb-2">
                  Welcome back, <span className="text-green-400">{userName}</span>! 👋
                </h2>
                <p className="text-zinc-400 text-lg">Select a track to start racing</p>
              </div>

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

              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {TRACKS.map((t, i) => {
                  const bestTime = scores[t.name];
                  return (
                    <button
                      key={t.name}
                      onClick={() => selectTrack(i)}
                      className="group relative bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 rounded-2xl p-4 transition-all hover:scale-[1.03] active:scale-[0.98]"
                    >
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
                        </svg>
                      </div>
                      <div className="text-center">
                        <div className="text-lg mb-1">{t.flag}</div>
                        <div className="font-bold text-sm group-hover:text-white transition">{t.name}</div>
                        <div className="text-xs text-zinc-500">{t.length}</div>
                        {bestTime && (
                          <div className="text-xs text-yellow-400 mt-1 font-mono">Best: {formatTime(bestTime)}</div>
                        )}
                      </div>
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
            </button>
            <div className="flex items-center gap-3">
              <div className="hidden sm:flex items-center gap-2 bg-white/5 px-3 py-1.5 rounded-full border border-white/10">
                <div className={`w-2 h-2 rounded-full ${s.racing ? "bg-red-500 animate-pulse" : "bg-green-400"}`} />
                <span className="text-sm text-zinc-300">
                  {s.racing ? "Racing..." : s.line.length > 0 ? "Ready to race" : "Draw your line"}
                </span>
              </div>
              <h1 className="text-lg font-bold">
                <span style={{ color: track.accent }}>🏎️</span>{" "}
                <span className="bg-gradient-to-r from-green-400 to-emerald-500 bg-clip-text text-transparent">Draw Line Racing</span>
              </h1>
            </div>
          </div>
        </header>

        <main className="max-w-7xl mx-auto p-4 sm:p-6">
          <div className="grid lg:grid-cols-[1fr_280px] gap-6">
            <div className="space-y-4">
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

              <div className="flex flex-wrap gap-3">
                <button onClick={clearLine} className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-5 py-3 bg-zinc-800 hover:bg-zinc-700 rounded-xl font-semibold transition-all border border-zinc-700">
                  Clear
                </button>
                <button onClick={startRace} disabled={s.racing} className="flex-1 sm:flex-none flex items-center justify-center gap-2 px-8 py-3 bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-400 hover:to-emerald-500 rounded-xl font-bold transition-all shadow-lg shadow-green-500/20 disabled:opacity-50 disabled:cursor-not-allowed">
                  {s.racing ? "Racing..." : "🏁 Start Race"}
                </button>
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
