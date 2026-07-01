import { useQuery } from "@tanstack/react-query";

import { Card } from "../components/ui/Card";
import { getHealth } from "../lib/api";

export function Home() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  return (
    <main className="page-shell">
      <header className="hero">
        <p className="eyebrow">LOCAL-FIRST AGENT HARNESS</p>
        <h1>Cyber Interview Agent</h1>
        <p className="subtitle">求职资料、模拟面试与可追溯 Agent 运行中心。</p>
      </header>

      <Card aria-labelledby="backend-status-title">
        <h2 id="backend-status-title">系统状态</h2>
        {health.isPending && <p aria-live="polite">正在连接后端…</p>}
        {health.isError && (
          <p className="status status-error" role="alert">
            无法连接后端，请确认本地服务已经启动。
          </p>
        )}
        {health.data && (
          <div className="status status-ok" role="status">
            <span className="status-dot" aria-hidden="true" />
            <div>
              <strong>后端运行正常</strong>
              <p>版本 {health.data.version}</p>
            </div>
          </div>
        )}
      </Card>
    </main>
  );
}

