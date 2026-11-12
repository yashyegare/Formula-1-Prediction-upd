import { useEffect, useRef, useState } from "react";
import { curveColor, profileSchema, type IntelDriver } from "src/lib/raceIntel";
import { useIntelResource } from "src/lib/useIntelResource";
import { ProbabilityChart } from "./ReplayPanel";
export default function DriverProfilePanel({
  driver,
  season,
  onClose,
}: {
  driver: IntelDriver;
  season: number;
  onClose: () => void;
}) {
  const [attempt, setAttempt] = useState(0),
    [round, setRound] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const resource = useIntelResource(
    `/api/race-intel/curves/${season}/driver/${encodeURIComponent(
      driver.driverId
    )}`,
    profileSchema,
    attempt
  );
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [driver.driverId]);
  const rounds = resource.data?.races ?? [];
  const selected = rounds.find((r) => r.round === round) ?? rounds.at(-1);
  return (
    <div
      className="ri-profile-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        id="driver-profile"
        className="ri-panel ri-driver-profile ri-profile-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-heading"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
            return;
          }
          if (event.key !== "Tab") return;
          const controls = [
            ...event.currentTarget.querySelectorAll<HTMLElement>(
              "button:not(:disabled),select:not(:disabled),a[href],input:not(:disabled)"
            ),
          ];
          const first = controls[0],
            last = controls.at(-1),
            active = document.activeElement;
          if (
            event.shiftKey &&
            (active === first || !controls.includes(active as HTMLElement))
          ) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && active === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
      >
        <div className="ri-section-heading">
          <div>
            <p className="ri-eyebrow">DRIVER DEEP DIVE</p>
            <h2 id="profile-heading" ref={heading} tabIndex={-1}>
              {driver.surname} · season replay
            </h2>
            <p>
              Explore this driver’s podium probability across completed rounds
              in the snapshot.
            </p>
          </div>
          <button
            className="ri-icon-button"
            onClick={onClose}
            aria-label="Close driver profile"
          >
            ×
          </button>
        </div>
        {resource.status === "loading" && (
          <p role="status" className="ri-empty">
            Loading driver traces…
          </p>
        )}
        {(resource.status === "empty" || resource.status === "error") && (
          <div className="ri-empty" role="status">
            <strong>No season traces available</strong>
            <p>
              {resource.error ??
                "This driver has no replay curves in the current snapshot."}
            </p>
            <button
              className="ri-button"
              onClick={() => setAttempt((n) => n + 1)}
            >
              Retry driver profile
            </button>
          </div>
        )}
        {resource.data &&
          (!rounds.length ? (
            <p className="ri-empty">
              There are no recorded replay rounds for this driver.
            </p>
          ) : (
            selected && (
              <>
                <label className="ri-profile-select">
                  Completed round
                  <select
                    value={selected.round}
                    onChange={(event) => setRound(Number(event.target.value))}
                  >
                    {rounds.map((r) => (
                      <option key={r.round} value={r.round}>
                        Round {r.round}
                        {r.final_position
                          ? ` · classified P${r.final_position}`
                          : " · classification unavailable"}
                      </option>
                    ))}
                  </select>
                </label>
                <ProbabilityChart
                  drivers={[
                    {
                      ...driver,
                      final_position: selected.final_position,
                      curve: selected.curve,
                    },
                  ]}
                  nLaps={selected.n_laps}
                  metric="podium"
                  selected={driver.driverId}
                  lap={selected.n_laps}
                />
                <p
                  className="ri-caption"
                  style={{ color: curveColor(driver.driverId) }}
                >
                  Podium probability · round {selected.round}. A missing final
                  position is not automatically labelled as a DNF.
                </p>
              </>
            )
          ))}
      </section>
    </div>
  );
}
