import { type AppType } from "next/app";

import "src/styles/globals.css";
import "src/styles/race-lab.css";
import "src/styles/home-experience.css";
import "src/styles/product-controls.css";
import "src/styles/finish.css";

const MyApp: AppType = ({ Component, pageProps }) => {
  return <Component {...pageProps} />;
};

export default MyApp;
