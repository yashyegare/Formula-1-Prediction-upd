import { z } from "zod";
const number = z.number().finite();
const count = number.int().nonnegative();
const probability = number.min(0).max(1);
export const postmortemSchema = z.object({
  season: count,
  races_scored: count,
  predictions_scored: count,
  hit_rate: probability.nullable(),
  verdict_share: z.record(z.string(), probability),
  races: z.array(
    z.object({
      round: count,
      name: z.string(),
      date: z.string(),
      predictions_scored: count,
      mean_abs_error: number.nullable(),
      verdict_counts: z.record(z.string(), count),
      misses: z.array(
        z.object({
          driverId: z.string(),
          surname: z.string(),
          predicted_position: number,
          actual_position: number.nullable(),
          verdict: z.string(),
          status: z.string(),
          grid_start: number.nullable(),
          sim_expected_position: number.nullable(),
        })
      ),
    })
  ),
});
export const reconcileSchema = z.object({
  season: count,
  has_simulated_standings: z.boolean(),
  rounds_in_artifact: count,
  raced_rounds: count,
  drivers: z.array(
    z.object({
      driverId: z.string(),
      surname: z.string(),
      driverCode: z.string(),
      constructorId: z.string(),
      simulated: number.nullable(),
      model_season: number,
      model_raced: number,
      actual_raced: number,
      sim_minus_model: number.nullable(),
      model_minus_actual: number,
    })
  ),
  totals: z.object({
    simulated: number.nullable(),
    model_season: number,
    model_raced: number,
    actual_raced: number,
  }),
});
