export interface ActionableError {
  message: string;
  advice: string;
}

export function toActionableError(caught: unknown, fallback: string): ActionableError {
  const message = caught instanceof Error ? caught.message : fallback;

  if (message.includes("Workspace Path")) {
    return { message, advice: "下一步：填写本地 workspace 路径" };
  }
  if (message.includes("请选择资料文件")) {
    return { message, advice: "下一步：选择一份 txt、Markdown 或 PDF 资料" };
  }
  if (message.includes("请输入你的回答")) {
    return { message, advice: "下一步：根据当前题目输入一段回答" };
  }
  if (message.includes("Failed to fetch")) {
    return {
      message: "后端未连接，请确认 FastAPI 服务已启动",
      advice: "下一步：运行 cd backend && uv run fastapi dev app/main.py",
    };
  }
  if (message.includes("重新扫描")) {
    return { message, advice: "下一步：确认 workspace 有效后重新扫描" };
  }
  if (message.includes("确认报告")) {
    return { message, advice: "下一步：先发送回答生成报告" };
  }

  return { message, advice: "下一步：检查当前步骤输入后重试" };
}
