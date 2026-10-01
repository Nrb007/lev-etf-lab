import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import { Overview } from "./pages/Overview";
import { Hypotheses } from "./pages/Hypotheses";
import { HypothesisDetail } from "./pages/HypothesisDetail";
import { JudgeValidation } from "./pages/JudgeValidation";
import { Method } from "./pages/Method";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/hypotheses", label: "Hypotheses" },
  { to: "/judge-validation", label: "Judge validation" },
  { to: "/method", label: "Method" },
];

export function Shell() {
  return (
    <div className="app">
      <header className="site-header">
        <span className="brand">lev-etf-lab</span>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/hypotheses" element={<Hypotheses />} />
          <Route path="/hypotheses/:id" element={<HypothesisDetail />} />
          <Route path="/demo/:id" element={<HypothesisDetail demo />} />
          <Route path="/judge-validation" element={<JudgeValidation />} />
          <Route path="/method" element={<Method />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
      <footer className="site-footer">
        Research system, not investment advice. Numbers come from deterministic code; see the Method page.
      </footer>
    </div>
  );
}

export default function App() {
  // Hash routing: a static host (GitHub Pages) needs no rewrite rules.
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  );
}
