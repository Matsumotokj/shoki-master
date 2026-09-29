import type { Answer, SummaryResult } from "../api/client";

type Props = { answer: Answer; result: SummaryResult };

const AXES = [
  { key: "faithfulness", label: "忠実性", max: 50 },
  { key: "coverage", label: "網羅性", max: 35 },
  { key: "clarity", label: "明瞭・簡潔", max: 15 },
] as const;

/** 要約の結果。観点ごとの点数、講評、自分の要約と模範要約の比較。 */
export function SummaryResultView({ answer, result }: Props) {
  return (
    <>
      <section className="card stack" style={{ gap: 18 }}>
        <div className="score">
          <span className="big mono">
            {result.score}
            <span className="unit">点</span>
          </span>
          <span className="sub">
            100 点満点 ・{" "}
            {result.penalty < 0 ? `長さによる減点 ${result.penalty}（${result.penalty_reasons.join("、")}）` : "長さによる減点なし"}
          </span>
          {result.hallucination ? (
            <span className="flag bad">元の文章にない内容が含まれています（上限 70 点）</span>
          ) : (
            <span className="flag">元の文章にない内容の付け足し: なし</span>
          )}
        </div>
        <div className="bars">
          {AXES.map(({ key, label, max }) => {
            const value = result.subscores[key];
            const ratio = value / max;
            return (
              <div key={key} className="bar">
                <span>{label}</span>
                <span className="meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
                  <i className={ratio < 0.6 ? "low" : undefined} style={{ width: `${ratio * 100}%` }} />
                </span>
                <span className="val mono">
                  {value} / {max}
                </span>
              </div>
            );
          })}
        </div>
        {result.notes && (
          <div>
            <div className="label">講評</div>
            <p style={{ marginTop: 4, fontSize: 14 }}>{result.notes}</p>
          </div>
        )}
      </section>

      <div className="compare">
        <section className="card">
          <div className="label">あなたの要約</div>
          <p>{answer.user_input}</p>
        </section>
        <section className="card">
          <div className="label">模範要約</div>
          <p>{result.best_summary}</p>
        </section>
      </div>

      <details className="card">
        <summary>元の文章を見る</summary>
        <p>{answer.source_text}</p>
      </details>
    </>
  );
}
