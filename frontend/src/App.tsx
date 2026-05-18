import { MagpieWindow } from "./components/MagpieWindow";
import { SettingsWindow } from "./components/SettingsWindow";

declare global {
  interface Window {
    __MAGPIE_WINDOW_TYPE__?: string;
  }
}

export default function App() {
  const isSettings = window.__MAGPIE_WINDOW_TYPE__ === "settings";
  return isSettings ? <SettingsWindow /> : <MagpieWindow />;
}
