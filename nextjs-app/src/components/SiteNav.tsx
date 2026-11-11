import Link from 'next/link';
export const SIMULATOR_URL = 'https://formula-1-prediction-upd-fxzg.vercel.app';
export default function SiteNav() {
  return <header className="lab-nav"><Link href="/" className="lab-brand" aria-label="F1 Race Lab home"><span aria-hidden="true">/</span> F1 RACE LAB</Link><nav aria-label="Main navigation"><Link href="/#predict">Predict</Link><a href={SIMULATOR_URL}>Simulate</a><Link href="/#results">Results</Link><Link href="/about">About</Link></nav></header>;
}
