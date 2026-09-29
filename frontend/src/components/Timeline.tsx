import type { SentenceMark } from "../lib/playback";
import { formatDuration } from "../lib/format";

type Props = {
  sentences: readonly SentenceMark[];
  currentMs: number;
  durationMs: number;
  currentIndex: number;
};

/** 進行バー。目盛りは各文の始まり（Polly の Speech Marks から得た位置）。 */
export function Timeline({ sentences, currentMs, durationMs, currentIndex }: Props) {
  const percent = (ms: number) => (durationMs > 0 ? Math.min(100, (ms / durationMs) * 100) : 0);

  return (
    <div>
      <div
        className="timeline"
        role="progressbar"
        aria-label="再生位置"
        aria-valuemin={0}
        aria-valuemax={Math.round(durationMs / 1000)}
        aria-valuenow={Math.round(currentMs / 1000)}
        aria-valuetext={`第 ${currentIndex + 1} 文、${formatDuration(currentMs)}`}
      >
        <div className="track" />
        <div className="fill" style={{ width: `${percent(currentMs)}%` }} />
        {sentences.map((s) => (
          <span key={s.index}>
            <div className={`tick${s.start_ms <= currentMs ? " passed" : ""}`} style={{ left: `${percent(s.start_ms)}%` }} />
            <span className="tick-label" style={{ left: `${percent(s.start_ms)}%` }}>
              {s.index + 1}
            </span>
          </span>
        ))}
        <div className="head" style={{ left: `${percent(currentMs)}%` }} />
      </div>
      <div className="timeinfo">
        <span>
          第 <b>{currentIndex + 1}</b> 文 / 全 {sentences.length} 文
        </span>
        <span className="mono">
          {formatDuration(currentMs)} / {formatDuration(durationMs)}
        </span>
      </div>
    </div>
  );
}
