import Link from "next/link";
import { useRouter } from "next/router";
import { TRACK_EXPLORER_BASE } from "../lib/trackExplorer";
export const SIMULATOR_URL = "https://formula-1-prediction-upd-fxzg.vercel.app";
export default function SiteNav() {
  const { pathname } = useRouter();
  return (
    <>
      <a className="lab-skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="lab-nav">
        <Link href="/" className="lab-brand" aria-label="F1 Race Lab home">
          <span aria-hidden="true">/</span> F1 RACE LAB
        </Link>
        <nav aria-label="Main navigation">
          <Link href="/#predict">Predict</Link>
          <a href={SIMULATOR_URL}>Simulate</a>
          <a href={TRACK_EXPLORER_BASE}>Tracks ↗</a>
          <Link
            href="/race-intel"
            aria-current={pathname === "/race-intel" ? "page" : undefined}
          >
            Analysis
          </Link>
          <Link
            href="/about"
            aria-current={pathname === "/about" ? "page" : undefined}
          >
            About
          </Link>
        </nav>
      </header>
    </>
  );
}
