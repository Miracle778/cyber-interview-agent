import path from "node:path";
import { fileURLToPath } from "node:url";

import concurrently from "concurrently";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(frontendDir, "..");

const { result } = concurrently(
  [
    {
      name: "backend",
      command:
        "uv run uvicorn cyber_interview.main:app --host 127.0.0.1 --port 8000 --reload",
      cwd: path.join(repoRoot, "backend"),
      prefixColor: "cyan",
    },
    {
      name: "frontend",
      command: "npm run dev",
      cwd: frontendDir,
      prefixColor: "magenta",
    },
  ],
  {
    killOthersOn: ["failure", "success"],
    restartTries: 0,
  },
);

try {
  await result;
} catch {
  process.exitCode = 1;
}

