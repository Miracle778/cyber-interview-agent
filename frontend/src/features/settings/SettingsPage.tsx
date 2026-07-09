import { Button } from "../../shared/ui/Button";
import { Field } from "../../shared/ui/Field";

export function SettingsPage() {
  return (
    <section aria-labelledby="settings-title">
      <h2 id="settings-title">设置</h2>
      <form>
        <Field label="Provider 名称" name="providerName" />
        <Field label="Base URL" name="baseUrl" />
        <Field label="Model ID" name="modelId" />
        <Field label="Workspace Path" name="workspacePath" />
        <Button>测试连接</Button>
        <Button>初始化工作区</Button>
      </form>
    </section>
  );
}
