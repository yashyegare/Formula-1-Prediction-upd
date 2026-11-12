import { z } from "zod";

const probability = z.number().finite().min(0).max(1);
export const intelDriverSchema = z.object({
  driverId: z.string(),
  driverCode: z.string(),
  surname: z.string(),
  constructorId: z.string(),
  grid: z.number().int().min(0),
  p_podium: probability,
  p_points: probability,
  p_out: probability,
  expected_position: z.number().finite().positive(),
  sim_dnf_rate: probability,
  actual_position: z.number().positive().nullable().optional(),
  is_dnf: z.boolean().optional(),
  observed_swing: z.number().nullable().optional(),
  sim_swing_mean: z.number().optional(),
});
export const intelRaceSchema = z.object({
  year: z.number().int(),
  round: z.number().int().positive(),
  name: z.string(),
  date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/)
    .refine((value) => Number.isFinite(Date.parse(value))),
  status: z.enum(["raced", "upcoming_post_quali", "scheduled"]),
  n_drivers: z.number().int().nonnegative(),
  drivers: z.array(intelDriverSchema),
  circuit: z
    .object({
      explorerSlug: z.string().nullable().optional(),
      name: z.string(),
      location: z.string(),
      country: z.string(),
    })
    .optional(),
});
const trackErrorSchema = z.object({
  n_rounds: z.number(),
  caveat: z.string(),
  correlation: z.record(
    z.string(),
    z.object({
      n: z.number(),
      pearson: z.number().nullable(),
      spearman: z.number().nullable(),
    })
  ),
  rounds: z.array(
    z.object({
      round: z.number(),
      name: z.string(),
      explorerSlug: z.string().nullable(),
      mean_abs_position_error: z.number(),
      dnf_rate: z.number(),
      n_scored: z.number(),
      cornerCount: z.number(),
      longestStraightMeters: z.number(),
      lengthMeters: z.number(),
      altitudeMeters: z.number(),
      drsZones: z.number(),
      direction: z.string(),
      continent: z.string(),
      firstGp: z.number(),
    })
  ),
});
export const intelSeasonSchema = z.object({
  season: z.number().int(),
  n_sims: z.number().int().positive(),
  next_round: z.number().nullable(),
  mechanism: z.object({
    swing_mean: z.number(),
    swing_sd: z.number(),
    dnf_rate: probability,
  }),
  races: z.array(intelRaceSchema),
  season_attribution: z.object({
    accuracy: probability,
    n_misses: z.number(),
    cause_share: z.record(z.string(), probability),
    evidence: z.record(z.string(), z.number()),
  }),
  track_error: trackErrorSchema.optional().catch(undefined),
});
export const intelCalendarSchema = z.object({
  season: z.number().int(),
  results_through_round: z.number().int().nonnegative().optional(),
  race: z.object({ round: z.number().int() }).optional(),
});
export const curvePointSchema = z.tuple([
  z.number().nonnegative(),
  probability,
  probability,
  probability,
  z.number().finite(),
]);
const lapDriverSchema = z.object({
  driverId: z.string(),
  driverCode: z.string().optional(),
  surname: z.string().optional(),
  final_position: z.number().nullable(),
  curve: z.array(curvePointSchema),
});
export const replaySchema = z.object({
  year: z.number().optional(),
  round: z.number(),
  n_laps: z.number().positive(),
  sample_laps: z.array(z.number()),
  drivers: z.array(lapDriverSchema),
});
export const profileSchema = z.object({
  season: z.number(),
  driverId: z.string(),
  driverCode: z.string(),
  surname: z.string(),
  races: z.array(
    z.object({
      round: z.number(),
      n_laps: z.number().positive(),
      sample_laps: z.array(z.number()),
      final_position: z.number().nullable(),
      curve: z.array(curvePointSchema),
    })
  ),
});
export type IntelSeason = z.infer<typeof intelSeasonSchema>;
export type IntelRace = z.infer<typeof intelRaceSchema>;
export type IntelDriver = z.infer<typeof intelDriverSchema>;
export type IntelCalendar = z.infer<typeof intelCalendarSchema>;
export type Replay = z.infer<typeof replaySchema>;
export type DriverProfile = z.infer<typeof profileSchema>;
export type CurvePoint = z.infer<typeof curvePointSchema>;

export const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
// Source buckets are mutually exclusive: podium / P4–10 / outside top ten.
export const topTenProbability = (driver: IntelDriver) =>
  Math.min(1, driver.p_podium + driver.p_points);
export const coverageRound = (season: IntelSeason) =>
  Math.max(
    0,
    ...season.races.filter((r) => r.status === "raced").map((r) => r.round)
  );
export function chooseRound(
  season: IntelSeason,
  calendar: IntelCalendar | null,
  requested?: number
) {
  if (requested && season.races.some((r) => r.round === requested))
    return requested;
  const completed = coverageRound(season);
  if (!calendar) return completed || season.races[0]?.round || null;
  if (
    calendar?.season === season.season &&
    (calendar.results_through_round ?? 0) > completed
  )
    return completed || season.races[0]?.round || null;
  return (
    season.races.find((r) => r.round === season.next_round)?.round ||
    completed ||
    season.races[0]?.round ||
    null
  );
}
export function raceLabel(race: IntelRace, officialRound: number | null) {
  if (race.status === "raced") return "Completed analysis";
  if (officialRound !== null && race.round <= officialRound)
    return "Archived projection";
  return race.status === "upcoming_post_quali"
    ? "Post-qualifying scenario"
    : "Pre-qualifying scenario";
}
export const expectedGain = (driver: IntelDriver) =>
  driver.grid > 0 ? driver.grid - driver.expected_position : null;
export const observedGain = (driver: IntelDriver) =>
  driver.grid > 0 && driver.actual_position != null
    ? driver.grid - driver.actual_position
    : null;
export function curveColor(id: string) {
  const colors = [
    "#a8372b",
    "#087f8c",
    "#7755a0",
    "#a66b08",
    "#2f68aa",
    "#b54776",
    "#537a35",
    "#69594d",
  ];
  const hash = [...id].reduce(
    (sum, c) => (sum * 31 + c.charCodeAt(0)) >>> 0,
    0
  );
  return colors[hash % colors.length] ?? colors[0]!;
}
export function visibleReplayDrivers(
  doc: Replay,
  order: string[],
  selected: string | null
) {
  const ranked = [...doc.drivers].sort((a, b) => {
    const ai = order.indexOf(a.driverId),
      bi = order.indexOf(b.driverId);
    return (
      (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) ||
      a.driverId.localeCompare(b.driverId)
    );
  });
  const shown = ranked.slice(0, 6),
    focused = doc.drivers.find((d) => d.driverId === selected);
  if (focused && !shown.some((d) => d.driverId === selected))
    shown.push(focused);
  return shown;
}
export const pointAtLap = (curve: CurvePoint[], lap: number) =>
  [...curve]
    .sort((a, b) => a[0] - b[0])
    .filter((point) => point[0] <= lap)
    .at(-1) ?? null;
export const teamName = (id: string) =>
  id.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
