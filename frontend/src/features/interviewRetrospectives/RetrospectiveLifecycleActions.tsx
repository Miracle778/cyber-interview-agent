import { useState } from "react";
import { Archive, Eraser, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import {
  clearSourceVersion,
  getRetrospectiveDeletionImpact,
  permanentlyDeleteRetrospective,
  transitionRetrospective,
} from "./retrospectiveApi";
import type { InterviewRetrospective, RetrospectiveDeletionImpact } from "./retrospectiveTypes";

export function RetrospectiveLifecycleActions({ retrospective, onChanged, onError }: {
  retrospective: InterviewRetrospective;
  onChanged: (kind: "lifecycle" | "source" | "deleted") => void;
  onError: (message: string) => void;
}) {
  const [dialog, setDialog] = useState<"clear" | "delete" | null>(null);
  const [impact, setImpact] = useState<RetrospectiveDeletionImpact | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: "archive" | "recycle" | "restore") {
    setBusy(true);
    try {
      await transitionRetrospective(retrospective.workspaceId, retrospective, action);
      onChanged("lifecycle");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "状态更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function openDelete() {
    setDialog("delete");
    setBusy(true);
    try {
      setImpact(await getRetrospectiveDeletionImpact(retrospective.workspaceId, retrospective.id));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "删除影响读取失败");
      setDialog(null);
    } finally {
      setBusy(false);
    }
  }

  async function clearSource() {
    setBusy(true);
    try {
      await clearSourceVersion(retrospective.workspaceId, retrospective);
      setDialog(null);
      onChanged("source");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "原文清除失败");
    } finally {
      setBusy(false);
    }
  }

  async function deleteForever() {
    setBusy(true);
    try {
      await permanentlyDeleteRetrospective(retrospective.workspaceId, retrospective);
      setDialog(null);
      onChanged("deleted");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "永久删除失败");
    } finally {
      setBusy(false);
    }
  }

  return <>
    <div className="retrospective-lifecycle-actions" aria-label="复盘管理">
      {retrospective.lifecycleStatus === "active" && retrospective.activeSourceVersionId && retrospective.activeSourceAvailable ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => setDialog("clear")}><Eraser size={15} />清除原文</Button> : null}
      {retrospective.lifecycleStatus === "active" ? <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("archive")}><Archive size={15} />归档</Button> : null}
      {["active", "archived"].includes(retrospective.lifecycleStatus) ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run("recycle")}><Trash2 size={15} />移到回收站</Button> : null}
      {["archived", "recycled"].includes(retrospective.lifecycleStatus) ? <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run("restore")}><RotateCcw size={15} />恢复</Button> : null}
      {retrospective.lifecycleStatus === "recycled" ? <Button size="sm" variant="danger" disabled={busy} onClick={() => void openDelete()}><Trash2 size={15} />永久删除</Button> : null}
    </div>
    {dialog === "clear" ? <div className="retrospective-confirm-backdrop" role="presentation"><section className="retrospective-confirm" role="dialog" aria-modal="true" aria-labelledby="clear-source-title"><TriangleAlert size={24} /><div><h3 id="clear-source-title">清除这份面试原文？</h3><p>清除后将无法再查看转写、核对原文引用，也不能基于这份原文重新整理或分析。</p><p>已确认的问题、结论、准备资产和行动项会保留。</p></div><footer><Button variant="ghost" onClick={() => setDialog(null)}>取消</Button><Button variant="danger" loading={busy} onClick={() => void clearSource()}>确认清除原文</Button></footer></section></div> : null}
    {dialog === "delete" ? <div className="retrospective-confirm-backdrop" role="presentation"><section className="retrospective-confirm" role="dialog" aria-modal="true" aria-labelledby="delete-retrospective-title"><TriangleAlert size={24} /><div><h3 id="delete-retrospective-title">永久删除这场复盘？</h3>{impact ? <><p>将删除这场复盘的 {impact.sourceVersions} 份原文、{impact.cleanupVersions} 个整理版本、{impact.analysisRuns} 次分析和 {impact.actionItems} 个行动项。</p><p>已进入复习题、个人画像、项目经历和知识库的内容不会被删除。</p></> : <p>正在读取删除范围…</p>}<label>输入“永久删除”以继续<input aria-label="永久删除确认" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoFocus /></label></div><footer><Button variant="ghost" onClick={() => { setDialog(null); setConfirmation(""); }}>取消</Button><Button variant="danger" loading={busy} disabled={!impact || confirmation !== "永久删除"} onClick={() => void deleteForever()}>永久删除</Button></footer></section></div> : null}
  </>;
}
