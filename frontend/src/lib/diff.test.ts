import { describe, expect, it } from "vitest";

import { summaryLengthRange, tallyDiff } from "./diff";

describe("tallyDiff", () => {
  it("種類ごとに区間の数を数える", () => {
    const tally = tallyDiff([
      { op: "equal", gold: "月間", typed: "月間" },
      { op: "replace", gold: "経常", typed: "計上" },
      { op: "equal", gold: "収益", typed: "収益" },
      { op: "delete", gold: "若干の", typed: "" },
      { op: "insert", gold: "", typed: "えー" },
      { op: "replace", gold: "供給", typed: "サプライ" },
    ]);
    expect(tally).toEqual({ replaced: 2, missed: 1, extra: 1 });
  });

  it("一致だけなら誤りは 0", () => {
    expect(tallyDiff([{ op: "equal", gold: "本日は", typed: "本日は" }])).toEqual({
      replaced: 0,
      missed: 0,
      extra: 0,
    });
  });
});

describe("summaryLengthRange", () => {
  it("元の文章の 25〜60% を目安にする（バックエンドの減点の基準と同じ）", () => {
    expect(summaryLengthRange(170)).toEqual({ min: 43, max: 102 });
  });
});
