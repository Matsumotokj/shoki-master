/**
 * 再生位置の計算（画面から切り離した純粋な関数）。
 *
 * 音声は題材全体で 1 本。各文の開始位置（start_ms）は Polly の Speech Marks から
 * 得ている。文の間には 350ms の無音を入れてあり、無音は「次の文の開始位置」の
 * 直前にある（SSML で <break/> を <mark/> の前に置いているため）。
 */

export type SentenceMark = { index: number; start_ms: number };

/** 句点区切りで止める位置を、次の文の開始位置からどれだけ手前にするか。 */
export const STOP_MARGIN_MS = 120;

/**
 * 再生位置 ms で読み上げ中の文の番号。最初の文より前なら 0。
 *
 * 文の数は多くても数十なので、先頭から数える単純な方法で十分。
 */
export function sentenceIndexAt(sentences: readonly SentenceMark[], ms: number): number {
  let current = 0;
  for (let i = 0; i < sentences.length; i++) {
    if (sentences[i]!.start_ms <= ms) current = i;
    else break;
  }
  return current;
}

/**
 * 句点区切りのとき、文 index をどこで止めるか。
 *
 * 次の文の開始位置の少し手前。文の間の無音（350ms）の中に入るので、声が途中で切れない。
 * ブラウザが知らせる再生位置は粗いので、画面の描画ごと（requestAnimationFrame）に確認する。
 * 最後の文は止めずに最後まで流す（null）。
 */
export function sentenceStopMs(sentences: readonly SentenceMark[], index: number): number | null {
  const next = sentences[index + 1];
  return next ? next.start_ms - STOP_MARGIN_MS : null;
}

/** 句点区切りで、今の位置がすでに文の終わり（止める位置）に達しているか。 */
export function isAtSentenceEnd(sentences: readonly SentenceMark[], ms: number): boolean {
  const stop = sentenceStopMs(sentences, sentenceIndexAt(sentences, ms));
  return stop !== null && ms >= stop - 10;
}

/** n 秒戻した位置。先頭より前にはしない。 */
export function rewindMs(ms: number, seconds: number): number {
  return Math.max(0, ms - seconds * 1000);
}
