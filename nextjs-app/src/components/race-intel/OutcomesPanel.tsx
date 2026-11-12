import { useMemo, useState } from "react";
import DriverPortrait from "../DriverPortrait";
import {
  expectedGain,
  observedGain,
  percent,
  teamName,
  topTenProbability,
  type IntelDriver,
  type IntelRace,
} from "src/lib/raceIntel";
import StateMessage from "./IntelStateMessage";
const NAMES: Record<string, string> = {
  RUS: "George Russell",
  ANT: "Andrea Kimi Antonelli",
  VER: "Max Verstappen",
  NOR: "Lando Norris",
  LEC: "Charles Leclerc",
  HAM: "Lewis Hamilton",
  PIA: "Oscar Piastri",
  ALO: "Fernando Alonso",
  STR: "Lance Stroll",
  SAI: "Carlos Sainz",
  ALB: "Alexander Albon",
  GAS: "Pierre Gasly",
  OCO: "Esteban Ocon",
  BEA: "Oliver Bearman",
  LAW: "Liam Lawson",
  HAD: "Isack Hadjar",
  HUL: "Nico Hulkenberg",
  BOR: "Gabriel Bortoleto",
  PER: "Sergio Perez",
  BOT: "Valtteri Bottas",
  LIN: "Arvid Lindblad",
  COL: "Franco Colapinto",
};
type Sort = "expected" | "podium" | "points" | "dnf" | "grid";
const signed = (value: number | null) =>
  value === null
    ? "—"
    : `${value > 0 ? "+" : ""}${
        Number.isInteger(value) ? value : value.toFixed(1)
      }`;
function Probability({
  value,
  kind,
}: {
  value: number;
  kind: "podium" | "points" | "dnf";
}) {
  return (
    <div className={`ri-probability ri-probability--${kind}`}>
      <span className="ri-probability-track" aria-hidden="true">
        <span style={{ width: `${value * 100}%` }} />
      </span>
      <strong>{percent(value)}</strong>
    </div>
  );
}

export default function OutcomesPanel({
  race,
  selectedDriver,
  onSelect,
}: {
  race: IntelRace;
  selectedDriver: string | null;
  onSelect: (driver: IntelDriver, trigger: HTMLButtonElement) => void;
}) {
  const [query, setQuery] = useState(""),
    [sort, setSort] = useState<Sort>("expected");
  const drivers = useMemo(
    () =>
      [...race.drivers].sort(
        (a, b) => a.expected_position - b.expected_position
      ),
    [race.drivers]
  );
  const displayed = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return drivers
      .filter((d) =>
        `${NAMES[d.driverCode] ?? d.surname} ${d.driverCode} ${teamName(
          d.constructorId
        )}`
          .toLowerCase()
          .includes(needle)
      )
      .sort((a, b) => {
        if (sort === "podium")
          return (
            b.p_podium - a.p_podium || a.expected_position - b.expected_position
          );
        if (sort === "points")
          return (
            topTenProbability(b) - topTenProbability(a) ||
            a.expected_position - b.expected_position
          );
        if (sort === "dnf")
          return (
            b.sim_dnf_rate - a.sim_dnf_rate ||
            a.expected_position - b.expected_position
          );
        if (sort === "grid") return (a.grid || 999) - (b.grid || 999);
        return a.expected_position - b.expected_position;
      });
  }, [drivers, query, sort]);

  return (
    <section className="ri-panel" aria-labelledby="outcomes-heading">
      <div className="ri-section-heading">
        <div>
          <p className="ri-eyebrow">THE FIELD, AT A GLANCE</p>
          <h2 id="outcomes-heading">Driver outcomes</h2>
          <p>
            Compare estimated chances. Open a driver to explore their season
            replay.
          </p>
        </div>
        <span className="ri-section-number" aria-hidden="true">
          01
        </span>
      </div>
      <div className="ri-table-tools">
        <label>
          Find a driver or team
          <input
            type="search"
            value={query}
            placeholder="Search the field…"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label>
          Sort by
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
          >
            <option value="expected">Average finish</option>
            <option value="podium">Podium probability</option>
            <option value="points">Top 10 probability</option>
            <option value="dnf">DNF risk</option>
            <option value="grid">Starting grid</option>
          </select>
        </label>
        <span role="status">
          {displayed.length} of {drivers.length} entries
        </span>
      </div>
      {!displayed.length ? (
        <StateMessage
          title="No matching drivers"
          message="Try a driver code, surname, or team name."
          retry={query ? () => setQuery("") : undefined}
        />
      ) : (
        <div
          className="ri-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Driver outcome table, scroll horizontally on small screens"
        >
          <table className="ri-outcomes-table">
            <caption className="ri-sr-only">
              {race.name} model outcome probabilities and recorded results
            </caption>
            <thead>
              <tr>
                <th scope="col">Grid</th>
                <th scope="col">Driver / team</th>
                <th scope="col" className="ri-numeric">
                  Avg. finish
                </th>
                <th scope="col">
                  Podium <small>P1–3</small>
                </th>
                <th scope="col">
                  Top 10 <small>includes podium</small>
                </th>
                <th scope="col">
                  DNF risk <small>separate estimate</small>
                </th>
                {race.status === "raced" && (
                  <th scope="col" className="ri-numeric">
                    Race result <small>places gained / lost</small>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {displayed.map((driver) => {
                const gained = observedGain(driver),
                  expected = expectedGain(driver);
                return (
                  <tr
                    key={driver.driverId}
                    data-selected={selectedDriver === driver.driverId}
                  >
                    <td className="ri-grid-cell">
                      {driver.grid > 0 ? `P${driver.grid}` : "Pit lane"}
                    </td>
                    <th scope="row">
                      <button
                        className="ri-driver-button"
                        onClick={(event) =>
                          onSelect(driver, event.currentTarget)
                        }
                        aria-expanded={selectedDriver === driver.driverId}
                        aria-controls="driver-profile"
                      >
                        <DriverPortrait
                          name={NAMES[driver.driverCode] ?? driver.surname}
                        />
                        <span>
                          <strong>
                            {driver.surname}
                            <small>{driver.driverCode}</small>
                          </strong>
                          <span>{teamName(driver.constructorId)}</span>
                        </span>
                        <span className="ri-driver-arrow" aria-hidden="true">
                          ↗
                        </span>
                      </button>
                    </th>
                    <td className="ri-numeric ri-average">
                      {driver.expected_position.toFixed(1)}
                    </td>
                    <td>
                      <Probability value={driver.p_podium} kind="podium" />
                    </td>
                    <td>
                      <Probability
                        value={topTenProbability(driver)}
                        kind="points"
                      />
                    </td>
                    <td>
                      <Probability value={driver.sim_dnf_rate} kind="dnf" />
                    </td>
                    {race.status === "raced" && (
                      <td className="ri-numeric ri-result">
                        <strong>
                          {driver.is_dnf
                            ? "DNF"
                            : driver.actual_position
                            ? `P${driver.actual_position}`
                            : "—"}
                        </strong>
                        <span
                          data-direction={
                            gained === null
                              ? "none"
                              : gained > 0
                              ? "gain"
                              : gained < 0
                              ? "loss"
                              : "none"
                          }
                        >
                          {signed(gained)} places
                        </span>
                        <small>model {signed(expected)}</small>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="ri-reading-note">
        <strong>Read the probabilities correctly.</strong>
        <p>
          Podium is included in Top 10. DNF risk is a separate simulated
          retirement estimate. The source’s “points” bucket means P4–10; Top 10
          here adds it to the podium bucket. Average finish is a mean across
          scenarios, not a precise finishing prediction. Positive place change
          means positions gained; pit-lane changes are omitted.
        </p>
      </div>
    </section>
  );
}
