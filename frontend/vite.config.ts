import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // ローカル開発では /api を uvicorn（backend/scripts/dev.py）へ中継する。
    // 本番では CloudFront が /api/* を API Gateway に振り分けるので、同じ形になる。
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
