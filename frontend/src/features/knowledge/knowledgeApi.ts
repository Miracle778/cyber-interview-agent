import type { ReviewQuestion } from "../review/reviewTypes";

export async function uploadSource(workspacePath: string, file: File): Promise<ReviewQuestion> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  form.set("file", file);
  const response = await fetch("/api/knowledge/sources", { method: "POST", body: form });
  if (!response.ok) throw new Error("上传失败");
  return response.json();
}
