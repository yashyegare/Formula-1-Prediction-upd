import { type NextPage } from "next";
import Head from "next/head";

import Docs from "src/components/docs";
import NextRoundCard from "src/components/NextRoundCard";
import Predictor from "../components/predictor";

const Home: NextPage = () => {
  return (
    <>
      <Head>
        <title>F1 Race Predictor</title>
        <meta name="description" content="ML-powered Formula 1 race result predictor" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main className="flex min-h-screen flex-col font-inter md:h-screen md:flex-row md:overflow-hidden">
        <section className="bg-[#161616] bg-[url('/red-bg.jpg')] bg-cover px-8 py-10 text-white md:flex md:h-full md:w-1/2 md:flex-col md:justify-center md:overflow-hidden md:px-10 md:py-4 xl:w-1/3">
          <Predictor />
        </section>
        <section className="flex flex-col p-6 md:h-full md:w-1/2 md:overflow-y-auto md:px-10 md:py-5 xl:w-2/3 xl:px-14">
          <article id="871047b8-2997-4a68-9c0f-53ade839e37d" className="page sans flex min-h-0 flex-col">
            <Docs nextRound={<NextRoundCard />} />
          </article>
        </section>
      </main>
    </>
  );
};

export default Home;
