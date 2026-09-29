import type { Answer, TranscriptionResult } from "../api/client";
import { tallyDiff } from "../lib/diff";

type Props = { answer: Answer; result: TranscriptionResult };

/**
 * 文字起こしの結果。誤りを、原稿に赤を入れるときの書き方で示す。
 * 正しい語に取り消し線を引いて書き違えた語を並べ、聞き落としには ⁁ を付ける。
 */
export function TranscriptionResultView({ answer, result }: Props) {
  const tally = tallyDiff(result.diff);

  return (
    <>
      <section className="card stack">
        <div className="score">
          <span className="big mono">
            {result.accuracy}
            <span className="unit">%</span>
          </span>
          <span className="sub">
            一致率 ・ 誤り <b className="mono">{result.distance}</b> 字 / <span className="mono">{result.length}</span> 字
          </span>
        </div>
        {tally.replaced + tally.missed + tally.extra > 0 ? (
          <div className="tally">
            {tally.replaced > 0 && <span>書き違い {tally.replaced} か所</span>}
            {tally.missed > 0 && <span>聞き落とし {tally.missed} か所</span>}
            {tally.extra > 0 && <span>余分 {tally.extra} か所</span>}
          </div>
        ) : (
          <p className="flag">すべて正確に書き取れています</p>
        )}
      </section>

      <section className="card stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ fontSize: 17 }}>校正</h3>
          <div className="legend">
            <span>
              <span className="rep">
                <s>正</s>
                <b>誤</b>
              </span>{" "}
              書き違い
            </span>
            <span>
              <span className="miss">語</span> 聞き落とし
            </span>
            <span>
              <span className="extra">語</span> 余分
            </span>
          </div>
        </div>
        <p className="proof">
          {result.diff.map((segment, i) => {
            switch (segment.op) {
              case "equal":
                return <span key={i}>{segment.gold}</span>;
              case "replace":
                return (
                  <span key={i} className="rep">
                    <s>{segment.gold}</s>
                    <b>{segment.typed}</b>
                  </span>
                );
              case "delete":
                return (
                  <span key={i} className="miss" title="聞き落とし">
                    {segment.gold}
                  </span>
                );
              case "insert":
                return (
                  <span key={i} className="extra" title="余分">
                    {segment.typed}
                  </span>
                );
            }
          })}
        </p>
        <details>
          <summary>元の文章とあなたの書き取りを並べて見る</summary>
          <div className="compare" style={{ marginTop: 10 }}>
            <div>
              <div className="label">元の文章</div>
              <p>{answer.source_text}</p>
            </div>
            <div>
              <div className="label">あなたの書き取り</div>
              <p>{answer.user_input}</p>
            </div>
          </div>
        </details>
      </section>
    </>
  );
}
