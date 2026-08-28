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
      </div>
    </nav>
  );
};

export default Nav;
