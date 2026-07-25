import { Layers3, X } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import type { DuplicateProposalPreview } from "./profileTypes";

export function ProfileDuplicateMergeDialog({
  preview,
  busy,
  onCancel,
  onConfirm,
}: {
  preview: DuplicateProposalPreview;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return <div className="dialog-backdrop profile-batch-dialog-backdrop" role="presentation">
    <section className="profile-batch-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-duplicate-dialog-title">
      <header>
        <span><Layers3 size={20} /></span>
        <div>
          <h2 id="profile-duplicate-dialog-title">整理重复的待确认信息</h2>
          <p>只合并名称和身份完全一致的未确认内容；已确认资料不会改变。</p>
        </div>
        <button type="button" aria-label="关闭" onClick={onCancel}><X size={19} /></button>
      </header>
      <div className="profile-duplicate-dialog__summary">
        <strong>{preview.groupCount}</strong>
        <span>组重复信息，共 {preview.proposalCount} 条，整理后保留 {preview.groupCount} 条供你确认。</span>
      </div>
      <ul className="profile-duplicate-dialog__groups">
        {preview.groups.slice(0, 6).map((group) => <li key={group.canonicalProposalId}>
          <strong>{group.label}</strong>
          <span>{group.proposalIds.length} 条内容 · {group.evidenceCount} 处原文依据</span>
        </li>)}
      </ul>
      <footer>
        <Button variant="secondary" onClick={onCancel}>暂不整理</Button>
        <Button loading={busy} onClick={onConfirm}>确认整理</Button>
      </footer>
    </section>
  </div>;
}
