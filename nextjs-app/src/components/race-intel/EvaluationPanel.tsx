import { percent, type IntelSeason } from "src/lib/raceIntel";

export default function EvaluationPanel({
  evaluation,
}: {
  evaluation: NonNullable<IntelSeason["evaluation"]>;
}) {
  const methods = [
    ["Scenario model", evaluation.model],
    ["Historical rates", evaluation.global_rates],
    ["Starting grid", evaluation.starting_grid],
  ] as const;
  return (
    <section className="ri-panel" aria-labelledby="evaluation-heading">
      <div className="ri-section-heading">
        <div>
          <p className="ri-eyebrow">MEASURED, NOT ASSUMED</p>
          <h2 id="evaluation-heading">How the model compares</h2>
          <p>
            {evaluation.n_entries.toLocaleString()} driver entries across{" "}
            {evaluation.n_races} completed races, through round{" "}
            {evaluation.results_through_round}. Training and historical rates
            use seasons through {evaluation.training_through_year}.
          </p>
        </div>
      </div>
      <div
        className="ri-table-scroll"
        role="region"
        aria-label="Model evaluation comparison"
        tabIndex={0}
      >
        <table className="ri-evaluation-table">
          <caption>
            Lower scores are better. All methods use the same completed-race
            entries.
          </caption>
          <thead>
            <tr>
              <th scope="col">Method</th>
              <th scope="col">Brier score</th>
              <th scope="col">Log loss</th>
              <th scope="col">Position MAE</th>
            </tr>
          </thead>
          <tbody>
            {methods.map(([name, scores]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td>{scores.brier.toFixed(3)}</td>
                <td>{scores.log_loss.toFixed(3)}</td>
                <td>
                  {"position_mae" in scores
                    ? scores.position_mae.toFixed(2)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ri-caption">
        Brier measures probability error across three exclusive outcomes: P1–3,
        P4–10 and outside top 10. Log loss penalizes confident mistakes.
        Position MAE is average finishing-position error. The starting-grid
        probability baseline is deterministic with the same small log-loss floor
        as the model.
      </p>
      <p className="ri-evaluation-ci">
        Model minus historical-rates Brier: race-bootstrap 95% interval{" "}
        <strong>
          {evaluation.brier_delta_vs_global_95ci
            .map((x) => x.toFixed(3))
            .join(" to ")}
        </strong>
        . Negative values favor the model.
      </p>
      <h3 className="ri-calibration-title">
        Do podium chances match outcomes?
      </h3>
      <div className="ri-calibration-list">
        {evaluation.podium_calibration.map((bin) => (
          <div key={bin.lower}>
            <strong>
              {Math.round(bin.lower * 100)}–{Math.round(bin.upper * 100)}% band
            </strong>
            <span>{percent(bin.predicted)} predicted</span>
            <span>{percent(bin.observed)} observed</span>
            <small>{bin.n} entries</small>
          </div>
        ))}
      </div>
      <p className="ri-caption">{evaluation.limitations}</p>
    </section>
  );
}
