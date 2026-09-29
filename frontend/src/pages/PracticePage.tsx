import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router";

import { api, errorMessage, MODE_LABEL, type Problem } from "../api/client";
import { formatDuration } from "../lib/format";

/** 練習画面（再生の制御・書き取り・結果は次の段階で作る）。 */
export function PracticePage() {
  const { problemId = "" } = useParams();
  const location = useLocation();
  const passed = (location.state as { problem?: Problem } | null)?.problem;

  const [problem, setProblem] = useState<Problem | null>(passed ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (problem?.problem_id === problemId) return;
    api
      .GET("/api/problems/{problem_id}", { params: { path: { problem_id: problemId } } })
      .then(({ data, error: body, response }) => {
        if (data) setProblem(data);
        else setError(errorMessage(response.status, body));
      })
      .catch(() => setError(errorMessage(undefined, undefined)));
  }, [problemId, problem?.problem_id]);

  if (error) {
    return (
      <section className="stack">
        <div className="banner error" role="alert">
          {error}
        </div>
        <p>
          <Link to="/">トップに戻る</Link>
        </p>
      </section>
    );
  }
  if (!problem) return <p className="note">読み込み中…</p>;

  return (
    <section className="stack">
      <div className="row note">
        <span className={`chip ${problem.mode}`}>{MODE_LABEL[problem.mode]}</span>
        <span className="mono">
          {problem.text.length} 字 ・ {problem.sentences.length} 文
          {problem.duration_ms != null && ` ・ ${formatDuration(problem.duration_ms)}`}
        </span>
      </div>
      <h2 style={{ fontSize: 22 }}>{problem.theme}</h2>
      <p className="note">（練習画面は次の段階で作ります）</p>
    </section>
  );
}
