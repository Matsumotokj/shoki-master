import type { useAudioPlayer } from "../hooks/useAudioPlayer";
import type { SentenceMark } from "../lib/playback";
import { Timeline } from "./Timeline";

type Player = ReturnType<typeof useAudioPlayer>;

type Props = {
  player: Player;
  sentences: readonly SentenceMark[];
  showText: boolean;
  onShowTextChange: (value: boolean) => void;
  onPlayRequest: () => void;
};

// 書き取りでは 0.8 倍でも速いことがあるので、0.5 倍まで用意する
const RATES = [0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5];
export const BACK_SECONDS = 5;

/** 再生の操作。通し再生と句点区切りで、出すボタンが変わる。 */
export function PlayerPanel({ player, sentences, showText, onShowTextChange, onPlayRequest }: Props) {
  const sentenceMode = player.mode === "sentence";
  const last = player.currentIndex >= sentences.length - 1;

  return (
    <section className="card player" aria-label="再生">
      <Timeline
        sentences={sentences}
        currentMs={player.currentMs}
        durationMs={player.durationMs}
        currentIndex={player.currentIndex}
      />

      <div className="controls">
        <button
          className="play"
          type="button"
          onClick={player.playing ? player.pause : onPlayRequest}
          aria-label={player.playing ? "一時停止" : "再生"}
        >
          {player.playing ? "❚❚" : "▶"}
        </button>
        {sentenceMode ? (
          <>
            <button className="btn quiet" type="button" onClick={player.replaySentence} disabled={!player.started}>
              ↺ この文をもう一度
            </button>
            <button className="btn ghost" type="button" onClick={player.nextSentence} disabled={last}>
              次の文へ ▶
            </button>
          </>
        ) : (
          <button className="btn quiet" type="button" onClick={() => player.back(BACK_SECONDS)} disabled={!player.started}>
            ↶ {BACK_SECONDS} 秒戻る
          </button>
        )}
      </div>

      <div className="settings">
        <div className="setting">
          <span className="label" id="mode-label">
            再生のしかた
          </span>
          <div className="seg" role="group" aria-labelledby="mode-label">
            <button type="button" aria-pressed={!sentenceMode} onClick={() => player.setMode("through")}>
              通し再生
            </button>
            <button type="button" aria-pressed={sentenceMode} onClick={() => player.setMode("sentence")}>
              句点区切り
            </button>
          </div>
        </div>
        <div className="setting">
          <span className="label" id="rate-label">
            速さ
          </span>
          <div className="seg" role="group" aria-labelledby="rate-label">
            {RATES.map((rate) => (
              <button key={rate} type="button" aria-pressed={player.rate === rate} onClick={() => player.setRate(rate)}>
                {rate.toFixed(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="setting">
          <span className="label">文字の表示</span>
          <label className="switch">
            <input type="checkbox" checked={showText} onChange={(e) => onShowTextChange(e.target.checked)} />
            読み上げ中の文を表示
          </label>
        </div>
      </div>

      <p className="keys">
        書き取りながら操作: <kbd>Esc</kbd> 再生/停止 ・ <kbd>Ctrl</kbd>+<kbd>←</kbd>{" "}
        {sentenceMode ? (
          <>
            この文をもう一度 ・ <kbd>Ctrl</kbd>+<kbd>Enter</kbd> 次の文へ
          </>
        ) : (
          `${BACK_SECONDS} 秒戻る`
        )}
      </p>
    </section>
  );
}
