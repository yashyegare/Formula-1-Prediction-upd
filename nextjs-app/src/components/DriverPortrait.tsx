import { useState } from "react";
import portraits from "../data/driver-portraits.json";

function Portrait({ name }: { name: string }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
  const src = (portraits as Record<string, string>)[key];
  const initials = name
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2);
  return (
    <span className="lab-driver-avatar" data-loaded={loaded} aria-hidden="true">
      <span className="lab-avatar-initials">{initials}</span>
      {src && !failed && (
        <img
          src={src}
          width={48}
          height={48}
          alt=""
          decoding="async"
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => {
            setFailed(true);
            setLoaded(false);
          }}
        />
      )}
    </span>
  );
}

export default function DriverPortrait({ name }: { name: string }) {
  // Reset image state immediately on selection; a late image from the previous
  // driver must never appear beside the new driver's name.
  return <Portrait key={name} name={name} />;
}
