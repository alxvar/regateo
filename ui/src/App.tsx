import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { Match } from "./pages/Match";
import { Overview } from "./pages/Overview";
import { Run } from "./pages/Run";

type Theme = "system" | "light" | "dark";

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem("theme") as Theme) || "system"; } catch { return "system"; }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch { /* storage unavailable */ }
  }, [theme]);
  return [theme, setTheme];
}

export function App() {
  const [theme, setTheme] = useTheme();
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">regateo</Link>
        <nav><NavLink to="/" end>Runs</NavLink></nav>
        <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)} aria-label="Theme">
          <option value="system">System theme</option><option value="light">Light</option><option value="dark">Dark</option>
        </select>
      </header>
      {/* key: charts that read CSS variables re-render when the theme changes */}
      <main key={theme}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/runs/:id" element={<Run />} />
          <Route path="/matches/:id" element={<Match />} />
          <Route path="*" element={<p className="muted">Not found. <Link to="/">Back to runs</Link></p>} />
        </Routes>
      </main>
    </>
  );
}
