import { describe, expect, it } from "vitest";

import { isAtSentenceEnd, rewindMs, sentenceIndexAt, sentenceStopMs, STOP_MARGIN_MS } from "./playback";

// サンプル問題（文字起こし）と同じ形: 3 文、最初の文は 12ms から始まる
const SENTENCES = [
  { index: 0, start_ms: 12 },
  { index: 1, start_ms: 4712 },
  { index: 2, start_ms: 9205 },
];

describe("sentenceIndexAt", () => {
  it.each([
    [0, 0], // 最初の文より前
    [12, 0],
    [4711, 0],
    [4712, 1], // ちょうど次の文の開始位置
    [9000, 1],
    [9205, 2],
    [17_000, 2], // 最後の文の途中
  ])("%i ms は第 %i 文", (ms, expected) => {
    expect(sentenceIndexAt(SENTENCES, ms)).toBe(expected);
  });

  it("文が無ければ 0", () => {
    expect(sentenceIndexAt([], 1000)).toBe(0);
  });
});

describe("sentenceStopMs", () => {
  it("次の文の開始位置の少し手前で止める", () => {
    expect(sentenceStopMs(SENTENCES, 0)).toBe(4712 - STOP_MARGIN_MS);
    expect(sentenceStopMs(SENTENCES, 1)).toBe(9205 - STOP_MARGIN_MS);
  });

  it("止める位置は文の間の無音（350ms）の中にある", () => {
    // 無音は次の文の開始位置の直前 350ms。そこから外れると声が途中で切れる
    expect(STOP_MARGIN_MS).toBeGreaterThan(0);
    expect(STOP_MARGIN_MS).toBeLessThan(350);
  });

  it("最後の文は止めない", () => {
    expect(sentenceStopMs(SENTENCES, 2)).toBeNull();
  });
});

describe("isAtSentenceEnd", () => {
  it("止める位置に達していれば真", () => {
    expect(isAtSentenceEnd(SENTENCES, 4712 - STOP_MARGIN_MS)).toBe(true);
  });

  it("文の途中なら偽", () => {
    expect(isAtSentenceEnd(SENTENCES, 2000)).toBe(false);
  });

  it("最後の文では常に偽（止める位置が無い）", () => {
    expect(isAtSentenceEnd(SENTENCES, 16_000)).toBe(false);
  });
});

describe("rewindMs", () => {
  it("指定の秒数だけ戻す", () => {
    expect(rewindMs(9000, 5)).toBe(4000);
  });

  it("先頭より前にはならない", () => {
    expect(rewindMs(3000, 5)).toBe(0);
  });
});
