import { defineConfig } from "@playwright/test";

const python = process.env.CYBER_E2E_PYTHON ?? "backend/.venv/bin/python";

export default defineConfig({
  testDir: "./tests/e2e",
  webServer: [
    {
      command: `${python} tests/e2e/support/mock_openai_provider.py`,
      url: "http://127.0.0.1:9017/health",
      reuseExistingServer: false,
    },
    {
      command: `${python} tests/e2e/support/start_backend.py`,
      url: "http://127.0.0.1:8017/api/health",
      reuseExistingServer: false,
    },
    {
      command: "CYBER_API_TARGET=http://127.0.0.1:8017 npm --prefix frontend run dev -- --port 5177",
      url: "http://127.0.0.1:5177",
      reuseExistingServer: false,
    },
  ],
  use: {
    baseURL: "http://127.0.0.1:5177",
  },
});
