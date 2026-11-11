import Head from 'next/head';
import Docs from '../components/docs';
import SiteNav from '../components/SiteNav';
export default function About() {
  return <div className="f1-site"><Head><title>About & Methodology — F1 Race Lab</title></Head><SiteNav /><main className="lab-main lab-about"><p className="lab-eyebrow">Behind the predictions</p><h1>A fan project built around race-day possibilities.</h1><p className="lab-intro">Predict driver outcomes, explore championship scenarios, and compare expectations with what actually happened. Model estimates and simulated scenarios are separate from official results.</p><section className="lab-about-tools"><h2>Explore further</h2><p><a href="/race-intel">Race Intelligence</a> · <a href="https://f1-track-metrics-lab.vercel.app">Track Explorer</a></p><details><summary>Experiments</summary><p><a href="/racing">Draw Line Racing</a> — a separate driving game, kept outside the prediction workflow.</p></details></section><Docs /></main></div>;
}
