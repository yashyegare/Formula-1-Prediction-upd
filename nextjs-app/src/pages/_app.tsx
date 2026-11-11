import { type AppType } from "next/app";

import "src/styles/globals.css";
import "src/styles/race-lab.css";

const MyApp: AppType = ({ Component, pageProps }) => {
  return <Component {...pageProps} />;
};

export default MyApp;
