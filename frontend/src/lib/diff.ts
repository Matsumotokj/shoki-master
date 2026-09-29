/**
 * 文字起こしの差分の集計（画面から切り離した純粋な関数）。
 *
 * API は区間単位の差分（equal / replace / delete / insert）を返す。
 * 画面では、それを校正の書き方で並べ、種類ごとの件数を出す。
 */
import type { DiffSegment } from "../api/client";

export type DiffTally = {
  /** 書き違い（聞き違い・表記の違い） */
  replaced: number;
  /** 聞き落とし */
  missed: number;
  /** 余分に書いたもの */
  extra: number;
};

export function tallyDiff(segments: readonly DiffSegment[]): DiffTally {
  const tally: DiffTally = { replaced: 0, missed: 0, extra: 0 };
  for (const segment of segments) {
    if (segment.op === "replace") tally.replaced++;
    else if (segment.op === "delete") tally.missed++;
    else if (segment.op === "insert") tally.extra++;
  }
  return tally;
}

/** 要約の長さの目安（元の文章の 25〜60%）。これを外れると自動で減点される。 */
export function summaryLengthRange(sourceLength: number): { min: number; max: number } {
  return { min: Math.ceil(sourceLength * 0.25), max: Math.floor(sourceLength * 0.6) };
}
