import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import {
  api,
  errorMessage,
  MODE_LABEL,
  type Mode,
  type Problem,
  type Sample,
  type Usage,
} from "../api/client";
import { formatDuration } from "../lib/format";

const MODE_DESCRIPTION: Record<Mode, string> = {
  transcription: "聞こえたとおりに書き取り、一致率で採点します。",
  summary: "要点をまとめ、忠実性・網羅性・明瞭さで採点します。",
};

export function TopPage() {
  const navigate = useNavigate();
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const [theme, setTheme] = useState("");
  const [targetLength, setTargetLength] = useState(300);
  const [info, setInfo] = useState("");
  const [mode, setMode] = useState<Mode>("transcription");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 最初の API 呼び出しで Lambda が起動する（コールドスタート）。サンプルの一覧を
    // 最初に取っておけば、利用者がサンプルを選ぶ頃には起動が済んでいる。
    void api.GET("/api/samples").then(({ data }) => setSamples(data ?? []));
    void api.GET("/api/usage").then(({ data }) => setUsage(data ?? null));
  }, []);

  const remaining = usage ? Math.min(usage.daily.remaining, usage.monthly.remaining) : null;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { data, error: body, response } = await api.POST("/api/problems", {
        body: { theme, target_length: targetLength, info, mode },
      });
      if (data) {
        // 作ったばかりの問題は渡してしまい、練習画面で取り直さない
        navigate(`/practice/${data.problem_id}`, { state: { problem: data satisfies Problem } });
        return;
      }
      setError(errorMessage(response.status, body));
    } catch {
      setError(errorMessage(undefined, undefined));
    }
    setSubmitting(false);
    void api.GET("/api/usage").then(({ data }) => setUsage(data ?? null));
  }

  return (
    <>
      <section className="hero">
        <p>生成 AI が話し言葉の題材を作り、読み上げます。書き取った文章や要約は、その場で採点されます。</p>
      </section>

      <section className="stack">
        <div className="label">すぐに試す（待ち時間なし）</div>
        {samples === null ? (
          <p className="note">読み込み中…</p>
        ) : (
          <div className="samples">
            {samples.map((sample) => (
              <article key={sample.problem_id} className="card sample">
                <div className="row">
                  <span className={`chip ${sample.mode}`}>{MODE_LABEL[sample.mode]}</span>
                  <span className="meta mono">
                    {sample.char_count} 字 ・ {sample.sentence_count} 文
                    {sample.duration_ms != null && ` ・ ${formatDuration(sample.duration_ms)}`}
                  </span>
                </div>
                <h3>{sample.theme}</h3>
                <p className="meta">{MODE_DESCRIPTION[sample.mode]}</p>
                <div>
                  <Link className="btn" to={`/practice/${sample.problem_id}`}>
                    練習を始める
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}

      {submitting ? (
        <section className="card generating" aria-live="polite">
          <div className="spinner" aria-hidden="true" />
          <h2 style={{ fontSize: 19 }}>題材を作り、音声にしています</h2>
          <p className="note">10 秒ほどかかります。このままお待ちください。</p>
        </section>
      ) : (
        <form className="card form" onSubmit={onSubmit}>
          <div className="stack" style={{ gap: 4 }}>
            <h2 style={{ fontSize: 20 }}>問題を作る</h2>
            <p className="note">テーマに沿った題材を生成し、音声にします。10 秒ほどかかります。</p>
          </div>

          <div className="field">
            <label htmlFor="theme">テーマ</label>
            <textarea
              id="theme"
              rows={2}
              required
              maxLength={200}
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              placeholder="例: IT 企業の株主総会で、社長が四半期の業績を報告する"
            />
          </div>

          <div className="field">
            <label htmlFor="length">文字数の目安</label>
            <div className="length-row">
              <input
                id="length"
                type="range"
                min={50}
                max={500}
                step={50}
                value={targetLength}
                onChange={(e) => setTargetLength(Number(e.target.value))}
              />
              <output htmlFor="length" className="mono">
                {targetLength} 字
              </output>
            </div>
            <div className="hint">300 字でおよそ 1 分の音声になります</div>
          </div>

          <div className="field">
            <label htmlFor="info">追加の指示（任意）</label>
            <input
              id="info"
              type="text"
              maxLength={200}
              value={info}
              onChange={(e) => setInfo(e.target.value)}
              placeholder="例: 専門用語を少し含める"
            />
          </div>

          <fieldset className="field" style={{ border: "none", padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>
              採点のしかた
            </legend>
            <div className="modes">
              {(["transcription", "summary"] as const).map((value) => (
                <label key={value} className="mode-opt">
                  <input
                    type="radio"
                    name="mode"
                    value={value}
                    checked={mode === value}
                    onChange={() => setMode(value)}
                  />
                  <b>{MODE_LABEL[value]}</b>
                  <span>{MODE_DESCRIPTION[value]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="note">
              {remaining === null ? "" : remaining > 0 ? (
                <>
                  本日あと <b className="mono">{remaining}</b> 問作れます
                </>
              ) : (
                "作問の上限に達しています。サンプル問題は引き続き使えます"
              )}
            </span>
            <button className="btn" type="submit" disabled={remaining === 0 || theme.trim() === ""}>
              問題を作る
            </button>
          </div>
        </form>
      )}
    </>
  );
}
