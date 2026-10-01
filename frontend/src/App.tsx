import { Link, Route, Routes } from "react-router";

import { PracticePage } from "./pages/PracticePage";
import { TopPage } from "./pages/TopPage";

export function App() {
  return (
    <>
      <header className="app-header">
        <div className="inner">
          <Link to="/" className="brand">
            書記マスター
          </Link>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<TopPage />} />
          <Route path="/practice/:problemId" element={<PracticePage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}

function NotFound() {
  return (
    <section className="card stack">
      <h2>ページが見つかりません</h2>
      <p>
        <Link to="/">トップに戻る</Link>
      </p>
    </section>
  );
}
