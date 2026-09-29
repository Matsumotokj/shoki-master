import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useParams } from "react-router";

import { api, errorMessage, MODE_LABEL, type Answer, type Problem } from "../api/client";
import { BACK_SECONDS, PlayerPanel } from "../components/PlayerPanel";
import { Subtitles } from "../components/Subtitles";
import { SummaryResultView } from "../components/SummaryResultView";
import { TranscriptionResultView } from "../components/TranscriptionResultView";
import { useAudioPlayer } from "../hooks/useAudioPlayer";
import { summaryLengthRange } from "../lib/diff";
import { formatDuration } from "../lib/format";

/** 署名付き URL の期限のどれだけ前に取り直すか */
const URL_REFRESH_MARGIN_MS = 60_000;

export function PracticePage() {
  const { problemId = "" } = useParams();
  const location = useLocation();
  const passed = (location.state as { problem?: Problem } | null)?.problem;

  const [problem, setProblem] = useState<Problem | null>(passed?.problem_id === problemId ? passed : null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // refresh: 音声 URL を取り直すだけのとき。失敗しても、書きかけの回答を残すため画面は替えない
  const fetchProblem = useCallback(
    async (refresh = false) => {
      try {
        const { data, error, response } = await api.GET("/api/problems/{problem_id}", {
          params: { path: { problem_id: problemId } },
        });
        if (data) setProblem(data);
        else if (!refresh) setLoadError(errorMessage(response.status, error));
      } catch {
        if (!refresh) setLoadError(errorMessage(undefined, undefined));
      }
    },
    [problemId],
  );

  useEffect(() => {
    if (problem?.problem_id !== problemId) void fetchProblem();
  }, [fetchProblem, problem?.problem_id, problemId]);

  // 署名付き URL は 1 時間で切れる。切れる前に問題を取り直して新しい URL にする
  useEffect(() => {
    if (!problem) return;
    const wait = Date.parse(problem.audio_url_expires_at) - Date.now() - URL_REFRESH_MARGIN_MS;
    const timer = setTimeout(() => void fetchProblem(true), Math.max(0, wait));
    return () => clearTimeout(timer);
  }, [fetchProblem, problem]);

  if (loadError) {
    return (
      <section className="stack">
        <div className="banner error" role="alert">
          {loadError}
        </div>
        <p>
          <Link to="/">トップに戻る</Link>
        </p>
      </section>
    );
  }
  if (problem?.problem_id !== problemId) return <p className="note">読み込み中…</p>;
  return <Practice key={problem.problem_id} problem={problem} />;
}

function Practice({ problem }: { problem: Problem }) {
  const [audioError, setAudioError] = useState(false);
  const player = useAudioPlayer({
    src: problem.audio_url,
    sentences: problem.sentences,
    durationMs: problem.duration_ms,
    onError: () => setAudioError(true),
  });
  const [showText, setShowText] = useState(true);
  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const onPlayRequest = useCallback(() => {
    player.toggle();
    inputRef.current?.focus();
  }, [player]);

  // 書き取りの手を止めずに操作できるキー。日本語の変換中（未確定の文字がある間）は
  // 何もしない。変換の確定や取り消しに使うキーを横取りしないため
  useEffect(() => {
    if (answer) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === "Escape") {
        event.preventDefault();
        player.toggle();
      } else if (event.ctrlKey && event.key === "ArrowLeft") {
        event.preventDefault();
        if (player.mode === "sentence") player.replaySentence();
        else player.back(BACK_SECONDS);
      } else if (event.ctrlKey && event.key === "Enter" && player.mode === "sentence") {
        event.preventDefault();
        player.nextSentence();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [answer, player]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    player.pause();
    setSubmitting(true);
    setError(null);
    try {
      const { data, error: body, response } = await api.POST("/api/problems/{problem_id}/answers", {
        params: { path: { problem_id: problem.problem_id } },
        body: { user_input: input },
      });
      if (data) {
        setAnswer(data);
        window.scrollTo({ top: 0 });
      } else {
        setError(errorMessage(response.status, body));
      }
    } catch {
      setError(errorMessage(undefined, undefined));
    }
    setSubmitting(false);
  }

  function retry() {
    setAnswer(null);
    setInput("");
    setError(null);
    player.reset();
    window.scrollTo({ top: 0 });
  }

  const summaryMode = problem.mode === "summary";
  const range = summaryLengthRange(problem.text.length);
  const length = input.trim().length;

  return (
    <>
      <div className="problem-head">
        <div className="meta">
          <span className={`chip ${problem.mode}`}>{MODE_LABEL[problem.mode]}</span>
          <span className="mono">
            {problem.text.length} 字 ・ {problem.sentences.length} 文
            {problem.duration_ms != null && ` ・ ${formatDuration(problem.duration_ms)}`}
          </span>
        </div>
        <h2>{problem.theme}</h2>
      </div>

      {answer ? (
        <>
          {answer.transcription && <TranscriptionResultView answer={answer} result={answer.transcription} />}
          {answer.summary && <SummaryResultView answer={answer} result={answer.summary} />}
          <div className="row">
            <button className="btn" type="button" onClick={retry}>
              同じ問題にもう一度
            </button>
            <Link className="btn ghost" to="/">
              新しい問題を作る
            </Link>
          </div>
        </>
      ) : (
        <>
          <PlayerPanel
            player={player}
            sentences={problem.sentences}
            showText={showText}
            onShowTextChange={setShowText}
            onPlayRequest={onPlayRequest}
          />
          {showText && <Subtitles sentences={problem.sentences} currentIndex={player.currentIndex} started={player.started} />}

          {audioError && (
            <div className="banner error" role="alert">
              音声を読み込めませんでした。ページを再読み込みしてください
            </div>
          )}
          {error && (
            <div className="banner error" role="alert">
              {error}
            </div>
          )}

          <form className="card answer" onSubmit={onSubmit}>
            <label htmlFor="answer" className="label">
              {summaryMode ? "要約" : "書き取り"}
            </label>
            <textarea
              id="answer"
              ref={inputRef}
              className="ruled"
              value={input}
              maxLength={2000}
              onChange={(e) => setInput(e.target.value)}
              placeholder={summaryMode ? "聞いた内容の要点をまとめてください" : "聞こえたとおりに書き取ってください"}
            />
            <div className="answer-foot">
              <span className="note mono">
                {length} 字
                {summaryMode && (
                  <span className={length > 0 && (length < range.min || length > range.max) ? "off-range" : undefined}>
                    {" "}
                    ・ 目安 {range.min}〜{range.max} 字（外れると減点）
                  </span>
                )}
              </span>
              <button className="btn" type="submit" disabled={submitting || length === 0}>
                {submitting ? "採点しています…" : "採点する"}
              </button>
            </div>
          </form>
        </>
      )}
    </>
  );
}
