import Head from 'next/head';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import Predictor from './predictor';
import SiteNav, { SIMULATOR_URL } from './SiteNav';

interface Race { id: string; name: string; date: string; round: string; completed: boolean }
interface Season {
  schedule: Race[];
  drivers: Array<{ id: string; givenName: string; familyName: string }>;
  raceResults: Record<string, Array<{ driverId: string; position: number }>>;
}
const formatDate = (date: string) => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });

export default function HomePage() {
  const [season, setSeason] = useState<Season | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const year = new Date().getUTCFullYear();
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    fetch(`/api/init?year=${year}`, { signal: controller.signal, cache: 'no-store' })
      .then(res => { if (!res.ok) throw new Error('Season unavailable'); return res.json() as Promise<Season>; })
      .then(setSeason)
      .catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [year, attempt]);
  const races = [...(season?.schedule ?? [])].sort((a, b) => Number(a.round) - Number(b.round));
  const completed = races.filter(r => r.completed);
  const next = races.find(r => !r.completed);
  const latest = completed[completed.length - 1];
  const podium = latest ? [...(season?.raceResults[latest.id] ?? [])].sort((a, b) => a.position - b.position).slice(0, 3) : [];

  return <div className="f1-site">
    <Head><title>F1 Race Lab — Predict the race. Explore the championship.</title><meta name="description" content="Explore the next Formula 1 race, predict driver outcomes, and simulate how your results change the championship." /></Head>
    <SiteNav />
    <main className="lab-main">
      <section className="lab-hero">
        <div><p className="lab-eyebrow">Your take on the next race</p><h1>One race.<br />A different championship.</h1><p className="lab-intro">Make a prediction, explore its championship impact, and come back to see how the race unfolded.</p><div className="lab-actions"><a className="lab-primary" href="#predict">Predict this race ↗</a><a className="lab-secondary" href={SIMULATOR_URL}>Simulate the championship</a></div><p className="lab-caption">Explore without an account. Sign in to save your simulator predictions.</p></div>
        <aside className="lab-weekend" aria-live="polite"><p className="lab-eyebrow">{next ? `Up next / Round ${next.round}` : season ? 'Season review' : 'Race calendar'}</p><h2>{next?.name ?? (season ? `${year} season complete` : failed ? 'Calendar unavailable' : 'Loading the next race…')}</h2>{next && <p className="lab-race-date">{formatDate(next.date)}</p>}{season && <p className="lab-caption">{latest ? `Results through round ${latest.round} · ${formatDate(latest.date)}` : 'No completed races yet.'}</p>}{failed && <p>We couldn’t load the calendar. <button className="lab-text-button" onClick={() => setAttempt(n => n + 1)}>Try again</button></p>}<div className="lab-rule" /><p className="lab-caption">Keep official results in place. Change the remaining races to see who can take the title.</p><a className="lab-text-link" href={SIMULATOR_URL}>Open season simulator →</a></aside>
      </section>
      <section id="predict" className="lab-predict-section"><div className="lab-section-heading"><p className="lab-eyebrow">01 / Make your call</p><h2>Where will your driver finish?</h2><p>Choose a driver and qualifying position. The model estimates an outcome category, rather than an exact finishing position.</p></div><div className="lab-predict-layout"><div className="lab-predictor"><Predictor defaultRace={next?.name} /></div><div className="lab-explainer"><h3>Start with a race. Follow the consequences.</h3><ol><li><strong>Predict an outcome</strong><p>Explore podium, points, or outside-the-points finishes based on qualifying and historical form.</p></li><li><strong>Build your scenario</strong><p>Arrange finishing positions in the simulator and watch driver and constructor standings change.</p><a href={SIMULATOR_URL} className="lab-text-link">Try a championship scenario →</a></li><li><strong>Compare after the flag</strong><p>Review race analysis and compare saved simulator predictions with actual results.</p><Link href="/race-intel" className="lab-text-link">Review race analysis →</Link></li></ol><p className="lab-method-note">An estimate, with uncertainty. Qualifying is a strong signal; incidents and reliability can change everything. <Link href="/about">Read the methodology</Link>.</p></div></div></section>
      <section id="results" className="lab-results"><div><p className="lab-eyebrow">Latest completed{latest ? ` / Round ${latest.round}` : ''}</p><h2>{latest?.name ?? (season ? 'No results yet' : 'Official results')}</h2><p className="lab-caption">{latest ? `${formatDate(latest.date)} · Official race classification` : 'Completed races will appear here as results are published.'}</p></div><ol className="lab-podium">{podium.map(r => { const d = season?.drivers.find(d => d.id === r.driverId); return <li key={r.driverId}><span>P{r.position}</span><strong>{d ? `${d.givenName} ${d.familyName}` : r.driverId.replaceAll('_', ' ')}</strong></li>; })}</ol><a href={SIMULATOR_URL} className="lab-text-link">See all results →</a></section>
    </main><footer className="lab-footer"><span>F1 Race Lab · An independent fan project by Yash Yegare</span><Link href="/about">About & methodology</Link></footer>
  </div>;
}
