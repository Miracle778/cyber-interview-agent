import { useEffect, useMemo, useState } from "react";
import { AlertCircle, ArrowLeftRight, CheckCircle2, Pause, Play } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import { TaskWorkspace, TaskWorkspacePane } from "../../shared/ui/TaskWorkspace";
import type { CleanupSegment, CleanupVersion, SegmentEdit, SpeakerRole } from "./retrospectiveTypes";

const ROLE_LABELS: Record<SpeakerRole, string> = {
  interviewer: "面试官",
  candidate: "我",
  unknown: "待确认",
};

function toEdit(segment: CleanupSegment): SegmentEdit {
  const { speakerRole, rawSpeakerLabel, displayName, body, sourceStart, sourceEnd, confidence, uncertaintyReason, ignored } = segment;
  return { speakerRole, rawSpeakerLabel, displayName, body, sourceStart, sourceEnd, confidence, uncertaintyReason, ignored };
}

export function CleanupWorkbench({
  cleanup,
  busy,
  onSave,
  onConfirm,
  onStop,
  onResume,
}: {
  cleanup: CleanupVersion;
  busy: boolean;
  onSave: (segments: SegmentEdit[], expectedVersion: number) => void;
  onConfirm: (expectedVersion: number) => void;
  onStop: () => void;
  onResume: () => void;
}) {
  const [segments, setSegments] = useState(cleanup.segments);
  const [selectedId, setSelectedId] = useState(cleanup.segments.find((item) => item.speakerRole === "unknown")?.id ?? cleanup.segments[0]?.id ?? null);

  useEffect(() => {
    setSegments(cleanup.segments);
    setSelectedId((current) => current && cleanup.segments.some((item) => item.id === current) ? current : cleanup.segments.find((item) => item.speakerRole === "unknown")?.id ?? cleanup.segments[0]?.id ?? null);
  }, [cleanup.id, cleanup.version, cleanup.segments]);

  const uncertainCount = useMemo(
    () => segments.filter((item) => !item.ignored && item.speakerRole === "unknown").length,
    [segments],
  );
  const canConfirm = cleanup.status === "review_pending" && uncertainCount === 0 && segments.some((item) => !item.ignored);
  const selected = segments.find((item) => item.id === selectedId) ?? null;

  function updateSegment(id: string, patch: Partial<CleanupSegment>) {
    setSegments((current) => current.map((item) => {
      if (item.id !== id) return item;
      const next = { ...item, ...patch };
      if (patch.speakerRole && patch.speakerRole !== "unknown") {
        next.displayName = ROLE_LABELS[patch.speakerRole];
        next.uncertaintyReason = null;
      }
      return next;
    }));
  }

  function swapRoles() {
    setSegments((current) => current.map((item) => {
      const speakerRole = item.speakerRole === "candidate" ? "interviewer" : item.speakerRole === "interviewer" ? "candidate" : "unknown";
      return { ...item, speakerRole, displayName: ROLE_LABELS[speakerRole] };
    }));
  }

  const running = ["queued", "running", "stopping"].includes(cleanup.status);
  const stopped = cleanup.status === "stopped";
  const failed = cleanup.status === "failed";

  return (
    <section className="cleanup-workbench" aria-labelledby="cleanup-workbench-title">
      <header className="cleanup-workbench__header">
        <div>
          <p>{running ? "Agent 正在整理" : cleanup.status === "confirmed" ? "整理结果已确认" : stopped ? "整理已停止" : failed ? "整理遇到问题" : "请核对整理结果"}</p>
          <h2 id="cleanup-workbench-title">说话人与对话段落</h2>
          <span>{running ? "已经完成的段落会持续保存，可以离开页面。" : uncertainCount ? `${uncertainCount} 段需要确认` : "所有保留段落都有明确说话人"}</span>
        </div>
        <div className="cleanup-workbench__actions">
          <Button variant="secondary" size="sm" onClick={swapRoles} disabled={busy || running}><ArrowLeftRight size={16} /> 对调双方身份</Button>
          {running ? <Button variant="secondary" size="sm" onClick={onStop} disabled={busy}><Pause size={16} /> 停止整理</Button> : null}
          {stopped ? <Button size="sm" onClick={onResume} disabled={busy}><Play size={16} /> 继续整理</Button> : null}
          {failed ? <Button size="sm" onClick={onResume} disabled={busy}><Play size={16} /> 重试未完成部分</Button> : null}
        </div>
      </header>

      {running ? <div className="cleanup-workbench__progress" role="status"><span /><div><strong>正在识别说话人和段落</strong><p>刷新或离开不会丢失已完成结果。</p></div></div> : null}

      <TaskWorkspace className="cleanup-workbench__workspace" labelledBy="cleanup-workbench-title">
        <TaskWorkspacePane className="cleanup-segment-list" aria-label="整理后的对话段落">
          {segments.length ? segments.map((segment) => (
            <button
              type="button"
              key={segment.id}
              className="cleanup-segment-list__item"
              data-selected={segment.id === selectedId}
              data-uncertain={segment.speakerRole === "unknown" && !segment.ignored}
              data-ignored={segment.ignored}
              onClick={() => setSelectedId(segment.id)}
            >
              <span>{segment.ordinal}</span>
              <div><strong>{ROLE_LABELS[segment.speakerRole]}</strong><p>{segment.body}</p></div>
              {segment.speakerRole === "unknown" && !segment.ignored ? <AlertCircle size={18} aria-label="需要确认" /> : <CheckCircle2 size={18} aria-label={segment.ignored ? "已忽略" : "已识别"} />}
            </button>
          )) : <div className="cleanup-workbench__empty"><p>{running ? "Agent 正在准备第一批段落。" : "当前没有可核对的段落。"}</p></div>}
        </TaskWorkspacePane>

        <TaskWorkspacePane className="cleanup-segment-detail" aria-label="当前段落详情">
          {selected ? (
            <div>
              <header><span>第 {selected.ordinal} 段</span>{selected.uncertaintyReason && !selected.ignored ? <strong><AlertCircle size={16} /> {selected.uncertaintyReason}</strong> : null}</header>
              <label><span>说话人</span><SelectControl aria-label={`第 ${selected.ordinal} 段说话人`} value={selected.speakerRole} disabled={busy || running || cleanup.status === "confirmed"} onChange={(event) => updateSegment(selected.id, { speakerRole: event.target.value as SpeakerRole })}><option value="interviewer">面试官</option><option value="candidate">我</option><option value="unknown">待确认</option></SelectControl></label>
              <label><span>显示名称</span><input value={selected.displayName} disabled={busy || running || cleanup.status === "confirmed"} onChange={(event) => updateSegment(selected.id, { displayName: event.target.value })} /></label>
              <label><span>对话内容</span><textarea value={selected.body} disabled={busy || running || cleanup.status === "confirmed"} onChange={(event) => updateSegment(selected.id, { body: event.target.value })} /></label>
              <label className="cleanup-segment-detail__ignore"><input type="checkbox" checked={selected.ignored} disabled={busy || running || cleanup.status === "confirmed"} onChange={(event) => updateSegment(selected.id, { ignored: event.target.checked })} /><span>忽略这段，不进入后续分析</span></label>
              <p className="cleanup-segment-detail__source">原文位置 {selected.sourceStart.toLocaleString("en-US")} - {selected.sourceEnd.toLocaleString("en-US")}</p>
            </div>
          ) : <div className="cleanup-workbench__empty"><p>选择一个段落开始核对。</p></div>}
        </TaskWorkspacePane>
      </TaskWorkspace>

      <footer className="cleanup-workbench__footer">
        <div>{uncertainCount ? <><AlertCircle size={18} /><span>还有 {uncertainCount} 段说话人待确认</span></> : <><CheckCircle2 size={18} /><span>可以确认本次整理结果</span></>}</div>
        <div><Button variant="secondary" onClick={() => onSave(segments.map(toEdit), cleanup.version)} disabled={busy || running || cleanup.status === "confirmed"}>保存修改</Button><Button onClick={() => onConfirm(cleanup.version)} disabled={busy || !canConfirm}>确认整理结果</Button></div>
      </footer>
    </section>
  );
}
