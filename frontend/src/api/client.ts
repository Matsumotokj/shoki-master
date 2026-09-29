/**
 * API の呼び出し。
 *
 * 型は docs/openapi.json から自動生成した schema.d.ts を使う（npm run gen:api）。
 * バックエンドの型を変えて生成し直すと、ここや画面のずれがコンパイルエラーになる。
 */
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type Problem = Schemas["ProblemResponse"];
export type Answer = Schemas["AnswerResponse"];
export type Sample = Schemas["SampleSummary"];
export type Usage = Schemas["UsageStatus"];
export type Mode = Problem["mode"];
export type CreateProblemRequest = Schemas["CreateProblemRequest"];
export type DiffSegment = Schemas["DiffSegment"];
export type TranscriptionResult = Schemas["TranscriptionResult"];
export type SummaryResult = Schemas["SummaryResult"];

// 同じオリジンの /api を呼ぶ（ローカルは Vite が中継、本番は CloudFront が振り分け）
export const api = createClient<paths>({ baseUrl: "" });

/** 失敗したときに画面に出す文。サーバーの説明があればそれを優先する。 */
export function errorMessage(status: number | undefined, body: unknown): string {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string" && status !== 500) return detail;
  switch (status) {
    case undefined:
      return "通信できませんでした。ネットワークの状態を確認してください";
    case 404:
      return "問題が見つかりません。作成から 1 日経つと削除されます";
    case 422:
      return "入力内容を確認してください";
    case 429:
      return "作問の上限に達しました";
    case 502:
      return "文章の生成または採点に失敗しました。時間をおいて再度お試しください";
    case 503:
      return "一時的に作問と要約の採点を停止しています";
    default:
      return "エラーが発生しました。時間をおいて再度お試しください";
  }
}

export const MODE_LABEL: Record<Mode, string> = {
  transcription: "文字起こし",
  summary: "要約",
};
