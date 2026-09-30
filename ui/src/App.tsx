import { Component, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";

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

/** Shows a render error instead of a blank page; resets when the route changes. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card">
        <h2>This page failed to render</h2>
        <p className="error mono">{this.state.error.message}</p>
        <p className="secondary">If the backend was updated, restart <span className="mono">regateo serve</span> and
          reload: the page may expect report fields an older server doesn't send.</p>
      </div>
    );
  }
}

export function App() {
  const location = useLocation();
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
        <ErrorBoundary key={location.pathname}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/runs/:id" element={<Run />} />
          <Route path="/matches/:id" element={<Match />} />
          <Route path="*" element={<p className="muted">Not found. <Link to="/">Back to runs</Link></p>} />
        </Routes>
        </ErrorBoundary>
      </main>
    </>
  );
}
