import type { Problem } from "../api/client";

type Props = {
  sentences: Problem["sentences"];
  currentIndex: number;
  started: boolean;
};

/**
 * 読み上げ中の文。まだ読まれていない文は伏せる。
 * 先の文まで見えると、聞く前に答えが読めてしまうため。
 */
export function Subtitles({ sentences, currentIndex, started }: Props) {
  return (
    <section className="card subtitles" aria-live="polite">
      <div className="label">読み上げ中の文</div>
      {!started ? (
        <p className="note">再生すると、読み上げ中の文がここに表示されます</p>
      ) : (
        <>
          {sentences.map((s) =>
            s.index < currentIndex ? (
              <p key={s.index} className="done">
                {s.text}
              </p>
            ) : s.index === currentIndex ? (
              <p key={s.index} className="now">
                {s.text}
              </p>
            ) : null,
          )}
          {currentIndex < sentences.length - 1 && (
            <p className="later" aria-label="まだ読み上げていない文">
              ・・・・・
            </p>
          )}
        </>
      )}
    </section>
  );
}
