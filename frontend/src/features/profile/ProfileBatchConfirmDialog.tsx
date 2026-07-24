import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { Button } from "../../shared/ui/Button";

export function ProfileBatchConfirmDialog({
  acceptedCount,
  excludedCount,
  busy,
  onCancel,
  onConfirm,
}: {
  acceptedCount: number;
  excludedCount: number;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return <div className="dialog-backdrop profile-batch-dialog-backdrop" role="presentation">
    <section className="profile-batch-dialog" role="dialog" aria-modal="true" aria-labelledby="profile-batch-dialog-title">
      <header>
        <span><CheckCircle2 size={20} /></span>
        <div><h2 id="profile-batch-dialog-title">确认当前筛选中的可靠信息</h2><p>只有来源完整、没有冲突的内容会进入个人画像。</p></div>
        <button type="button" aria-label="关闭" onClick={onCancel}><X size={19} /></button>
      </header>
      <div className="profile-batch-dialog__body">
        <div><strong>{acceptedCount}</strong><span>条可以直接确认</span></div>
        <div><strong>{excludedCount}</strong><span>条需要逐项核对</span></div>
      </div>
      {excludedCount ? <p className="profile-batch-dialog__notice"><AlertTriangle size={16} />有冲突或缺少原文来源的内容不会被自动确认，仍会留在待确认列表。</p> : null}
      <footer>
        <Button variant="secondary" onClick={onCancel}>返回检查</Button>
        <Button loading={busy} disabled={!acceptedCount} onClick={onConfirm}>确认 {acceptedCount} 条信息</Button>
      </footer>
    </section>
  </div>;
}
