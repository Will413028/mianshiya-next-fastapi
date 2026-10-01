import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../../tests/e2e",
  timeout: 120000,
  expect: { timeout: 20000 },
  use: {
    baseURL: process.env.E2E_ORIGIN || "http://localhost:33017",
    trace: "off",
  },
  reporter: [["list"], ["json", { outputFile: "../../reports/e2e.json" }]],
  workers: 1,
});
