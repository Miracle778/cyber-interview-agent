import { useState, type ChangeEvent, type FormEvent } from "react";
import { FileText, Plus } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { SelectControl } from "../../shared/ui/SelectControl";
import type { JobTarget } from "../jobTargets/jobTargetTypes";
import type { RecordingCoverage, SourceKind } from "./retrospectiveTypes";

export interface RetrospectiveCreateValues {
  targetId: string;
  title: string;
  roundLabel: string;
  interviewDate: string | null;
  sourceKind: SourceKind;
  recordingCoverage: RecordingCoverage;
  body: string;
  fileName: string | null;
}

export function RetrospectiveCreateFlow({
  targets,
  initialTargetId = "",
  busy,
  onCancel,
  onCreateTarget,
  onSubmit,
}: {
  targets: JobTarget[];
  initialTargetId?: string;
  busy: boolean;
  onCancel: () => void;
  onCreateTarget: (input: {
    companyName: string;
    roleName: string;
    seniority: string;
  }) => Promise<JobTarget>;
  onSubmit: (values: RetrospectiveCreateValues) => void;
}) {
  const [targetId, setTargetId] = useState(initialTargetId);
  const [title, setTitle] = useState("");
  const [roundLabel, setRoundLabel] = useState("");
  const [interviewDate, setInterviewDate] = useState("");
  const [sourceKind, setSourceKind] = useState<SourceKind>("transcript");
  const [recordingCoverage, setRecordingCoverage] = useState<RecordingCoverage>("mixed_unknown");
  const [body, setBody] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creatingTarget, setCreatingTarget] = useState(false);
  const [targetDraft, setTargetDraft] = useState({
    companyName: "",
    roleName: "",
    seniority: "",
  });

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!/\.(txt|md|markdown)$/i.test(file.name)) {
      setError("仅支持 TXT 或 Markdown 文字文件");
      event.target.value = "";
      return;
    }
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.onerror = () => reject(reader.error ?? new Error("读取文件失败"));
      reader.readAsText(file);
    });
    if (text.length > 500_000) {
      setError("面试文字不能超过 500,000 个字符");
      return;
    }
    setBody(text);
    setFileName(file.name);
    setError(null);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!targetId) return setError("请选择求职目标");
    if (!title.trim()) return setError("请填写复盘名称");
    if (!roundLabel.trim()) return setError("请填写面试轮次");
    if (!body.trim()) return setError("请粘贴或导入面试文字");
    if (body.length > 500_000) {
      return setError("面试文字不能超过 500,000 个字符");
    }
    setError(null);
    onSubmit({
      targetId,
      title: title.trim(),
      roundLabel: roundLabel.trim(),
      interviewDate: interviewDate || null,
      sourceKind,
      recordingCoverage: sourceKind === "transcript" ? recordingCoverage : "mixed_unknown",
      body,
      fileName,
    });
  }

  return (
    <div className="retrospective-create" role="dialog" aria-modal="true" aria-labelledby="retrospective-create-title">
      <form onSubmit={submit}>
        <header>
          <div>
            <p>新建复盘</p>
            <h2 id="retrospective-create-title">先保存文字，再交给 Agent 整理</h2>
          </div>
          <button type="button" className="retrospective-icon-button" onClick={onCancel} aria-label="关闭新建复盘">×</button>
        </header>

        <div className="retrospective-create__body">
          <section className="retrospective-create__metadata" aria-label="复盘基本信息">
            <label>
              <span>求职目标</span>
              <SelectControl aria-label="求职目标" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                <option value="">请选择求职目标</option>
                {targets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {[target.companyName, target.roleName].filter(Boolean).join(" / ") || "岗位信息待补充"}
                  </option>
                ))}
              </SelectControl>
            </label>
            <button type="button" className="retrospective-create__inline-action" onClick={() => setCreatingTarget((value) => !value)}>
              <Plus size={16} /> 快速新建求职目标
            </button>
            {creatingTarget ? (
              <div className="retrospective-create__target-draft">
                <label><span>公司（可选）</span><input aria-label="公司" value={targetDraft.companyName} onChange={(event) => setTargetDraft({ ...targetDraft, companyName: event.target.value })} /></label>
                <label><span>岗位</span><input value={targetDraft.roleName} onChange={(event) => setTargetDraft({ ...targetDraft, roleName: event.target.value })} /></label>
                <label><span>经验或职级（可选）</span><input aria-label="经验或职级" value={targetDraft.seniority} onChange={(event) => setTargetDraft({ ...targetDraft, seniority: event.target.value })} /></label>
                <Button size="sm" variant="secondary" disabled={!targetDraft.roleName.trim()} onClick={async () => {
                  const target = await onCreateTarget(targetDraft);
                  setTargetId(target.id);
                  setCreatingTarget(false);
                }}>保存目标</Button>
              </div>
            ) : null}
            <label><span>复盘名称</span><input aria-label="复盘名称" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：星河科技后端一面" /></label>
            <div className="retrospective-create__row">
              <label><span>面试轮次</span><input aria-label="面试轮次" value={roundLabel} onChange={(event) => setRoundLabel(event.target.value)} placeholder="例如：技术二面" /></label>
              <label><span>面试日期</span><input aria-label="面试日期" type="date" value={interviewDate} onChange={(event) => setInterviewDate(event.target.value)} /></label>
            </div>
          </section>

          <section className="retrospective-create__source" aria-label="面试文字来源">
            <fieldset>
              <legend>这份文字从哪里来？</legend>
              <label data-selected={sourceKind === "transcript"}><input type="radio" name="source-kind" checked={sourceKind === "transcript"} onChange={() => setSourceKind("transcript")} /><strong>录音转写</strong><span>保留原对话顺序，Agent 会整理说话人和段落。</span></label>
              <label data-selected={sourceKind === "recollection"}><input type="radio" name="source-kind" checked={sourceKind === "recollection"} onChange={() => setSourceKind("recollection")} /><strong>事后回忆</strong><span>按现有文字整理，不补写没有记录的对话。</span></label>
            </fieldset>
            {sourceKind === "transcript" ? (
              <fieldset className="retrospective-create__coverage">
                <legend>这份转写包含谁的声音？</legend>
                <label data-selected={recordingCoverage === "full_dialogue"}><input type="radio" name="recording-coverage" checked={recordingCoverage === "full_dialogue"} onChange={() => setRecordingCoverage("full_dialogue")} /><strong>包含双方对话</strong><span>问题和回答基本都被录入。</span></label>
                <label data-selected={recordingCoverage === "candidate_only"}><input type="radio" name="recording-coverage" checked={recordingCoverage === "candidate_only"} onChange={() => setRecordingCoverage("candidate_only")} /><strong>主要只有我的讲话</strong><span>Agent 会根据回答谨慎反推可能的问题。</span></label>
                <label data-selected={recordingCoverage === "mixed_unknown"}><input type="radio" name="recording-coverage" checked={recordingCoverage === "mixed_unknown"} onChange={() => setRecordingCoverage("mixed_unknown")} /><strong>不确定或混合内容</strong><span>仅依据实际文字判断，不补写缺失对话。</span></label>
              </fieldset>
            ) : null}
            <label className="retrospective-create__text">
              <span>面试文字</span>
              <textarea aria-label="面试文字" value={body} maxLength={500_000} onChange={(event) => { setBody(event.target.value); setFileName(null); setError(null); }} placeholder="粘贴手机录音转写，或按顺序写下你记得的问答。" />
            </label>
            <div className="retrospective-create__source-actions">
              <label className="retrospective-file-button"><FileText size={16} /><span>导入 TXT / Markdown</span><input aria-label="导入文字文件" type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" onChange={importFile} /></label>
              <span>{body.length.toLocaleString("en-US")} / 500,000 字符</span>
            </div>
            {fileName ? <p className="retrospective-create__file-name">已导入：{fileName}</p> : null}
          </section>
        </div>
        {error ? <p className="retrospective-form-error" role="alert">{error}</p> : null}
        <footer><Button type="button" variant="secondary" onClick={onCancel}>取消</Button><Button type="submit" loading={busy}>开始整理</Button></footer>
      </form>
    </div>
  );
}
