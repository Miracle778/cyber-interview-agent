import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { SettingsPage } from "../../features/settings/SettingsPage";

export function AppShell() {
  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <p>复习闭环 MVP</p>
      <SettingsPage />
      <KnowledgePage />
    </main>
  );
}
