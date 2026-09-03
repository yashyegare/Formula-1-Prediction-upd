import Link from "next/link";
import { useRouter } from "next/router";

const LINKS = [
  { href: "/", label: "Predictor" },
];

const Nav = () => {
  const router = useRouter();

  const linkClass = (active: boolean) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
      active
        ? "bg-red-500/20 text-red-400"
        : "text-zinc-400 hover:bg-stone-800 hover:text-white"
    }`;

  return (
    <nav className="sticky top-0 z-20 flex items-center justify-between border-b border-stone-800 bg-[#161616]/95 px-6 py-3 backdrop-blur">
      <Link href="/" className="flex items-center gap-2 text-sm font-semibold text-white">
        <span className="text-lg">🏎️</span> F1 Race Predictor
      </Link>
      <div className="flex items-center gap-1">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} className={linkClass(router.pathname === l.href)}>
            {l.label}
          </Link>
        ))}
        <a
          href="https://f1-track-metrics-lab.vercel.app"
          target="_blank"
          rel="noreferrer"
          className="ml-2 flex items-center gap-1.5 rounded-lg border border-stone-700/60 bg-stone-800/40 px-3 py-1.5 text-sm font-medium text-zinc-300 transition hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-400"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M2 12h20" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
          Track Explorer
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none" className="opacity-50">
            <path d="M3 9L9 3M9 3H4.5M9 3V7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
      </div>
    </nav>
  );
};

export default Nav;
