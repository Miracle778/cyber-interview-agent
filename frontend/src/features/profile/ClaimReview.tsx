import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, FileSearch, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { Button } from "../../shared/ui/Button";
import { batchDecideClaimProposals, decideClaimProposal } from "./profileApi";
import type { ClaimDecision, ProfileClaimProposal, ProfileClaimReview, ProfileClaimWorkspace, ProfileEvidence } from "./profileTypes";
import { ClaimDiff } from "./ClaimDiff";
import { formatEvidenceLocator } from "./evidenceLocator";

type PendingDecision = { decision: ClaimDecision; expectedVersion: number };

function proposalClaim(snapshot: ProfileClaimWorkspace, proposal: ProfileClaimProposal) {
  return snapshot.claims.find((claim) => claim.id === proposal.targetClaimId || claim.proposals.some((item) => item.id === proposal.id)) ?? null;
}

function labelForClaimType(value: string) {
  const labels: Record<string, string> = { skill: "技能", project: "项目经历", experience: "工作经历", education: "教育", achievement: "成果" };
  return labels[value] ?? value;
}

export function ClaimReview({ workspaceId, snapshot, loading = false, onRefresh, onOpenEvidence, onOpenDeletion }: { workspaceId: string; snapshot: ProfileClaimWorkspace | null; loading?: boolean; onRefresh: () => Promise<unknown> | void; onOpenEvidence: (evidence: ProfileEvidence) => void; onOpenDeletion: () => void }) {
  const [status, setStatus] = useState("pending");
  const [category, setCategory] = useState("all");
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, PendingDecision>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const proposals = snapshot?.proposals ?? [];
  const categories = useMemo(() => [...new Set((snapshot?.claims ?? []).map((claim) => claim.claimType))], [snapshot]);
  const filtered = proposals.filter((proposal) => {
    const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
    return (status === "all" || proposal.status === status) && (category === "all" || claim?.claimType === category || (!claim && category === "new"));
  });
  const selected = filtered.find((item) => item.id === selectedProposalId) ?? filtered[0] ?? null;
  const selectedClaim = selected && snapshot ? proposalClaim(snapshot, selected) : null;
  const conflict = selected && selectedClaim?.conflicts.some((item) => item.proposalId === selected.id);

  async function decide(proposal: ProfileClaimProposal, decision: ClaimDecision, claim: ProfileClaimReview | null) {
    setBusy(proposal.id);
    setNotice(null);
    try {
      await decideClaimProposal(workspaceId, proposal.id, decision, claim?.version ?? 0);
      setPending((value) => { const next = { ...value }; delete next[proposal.id]; return next; });
      await onRefresh();
    } catch (error) {
      if (error instanceof ApiError && error.code.includes("conflict")) {
        setNotice("该画像项已更新，已为你刷新；其他待处理选择仍保留。");
        await onRefresh();
      } else setNotice(error instanceof Error ? error.message : "决定没有保存，请重试");
    } finally { setBusy(null); }
  }

  async function submitBatch() {
    const entries = Object.entries(pending);
    if (!entries.length) return;
    setBusy("batch");
    setNotice(null);
    try {
      const result = await batchDecideClaimProposals(workspaceId, entries.map(([proposalId, item]) => ({ proposalId, ...item })));
      const completed = new Set(result.items.filter((item) => item.status === "completed").map((item) => item.proposalId));
      setPending((value) => Object.fromEntries(Object.entries(value).filter(([id]) => !completed.has(id))));
      if (result.items.some((item) => item.status === "conflict")) setNotice("部分画像项已变化，冲突项已刷新并保留选择，请重新核对。");
      await onRefresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "批量决定没有保存"); }
    finally { setBusy(null); }
  }

  if (loading) return <div className="profile-loading" role="status"><p>正在读取画像建议…</p></div>;

  return <section className="claim-review">
    <header className="claim-review__toolbar">
      <div><h2>画像与经历</h2><p>核对每条建议的证据，再确认、拒绝或批量处理。</p></div>
      <Button variant="danger" onClick={onOpenDeletion}><ShieldAlert size={16} />永久删除材料</Button>
    </header>
    <div className="claim-review__filters" aria-label="画像筛选">
      <label>状态<select aria-label="按状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="pending">待确认</option><option value="accepted">已确认</option><option value="rejected">已拒绝</option><option value="all">全部</option></select></label>
      <label>分类<select aria-label="按分类筛选" value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部分类</option><option value="new">新建画像项</option>{categories.map((item) => <option key={item} value={item}>{labelForClaimType(item)}</option>)}</select></label>
      <span><strong>{proposals.filter((item) => item.status === "pending").length}</strong> 条待确认</span>
      <Button variant="ghost" size="sm" onClick={() => void onRefresh()}><RefreshCw size={15} />刷新</Button>
    </div>
    {notice ? <div className="claim-review__notice" role="status"><AlertTriangle size={17} />{notice}</div> : null}
    <div className="claim-review__workspace">
      <aside className="claim-review__queue" aria-label="建议队列">
        {filtered.length ? filtered.map((proposal) => {
          const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
          const hasConflict = claim?.conflicts.some((item) => item.proposalId === proposal.id);
          return <button key={proposal.id} type="button" aria-current={selected?.id === proposal.id} onClick={() => setSelectedProposalId(proposal.id)}>
            <span><strong>{labelForClaimType(claim?.claimType ?? "新画像项")}</strong><small>{proposal.reason || "AI 提取建议"}</small></span>
            <span className={hasConflict ? "claim-review__badge claim-review__badge--warning" : "claim-review__badge"}>{hasConflict ? <><AlertTriangle size={13} />存在冲突</> : proposal.status === "pending" ? "待确认" : proposal.status}</span><ChevronRight size={16} />
          </button>;
        }) : <div className="claim-review__empty"><CheckCircle2 size={24} /><strong>当前筛选下没有待处理建议</strong><p>你可以切换状态或分类查看其他画像项。</p></div>}
      </aside>
      <main className="claim-review__detail">
        {selected ? <>
          <header><div><span>{labelForClaimType(selectedClaim?.claimType ?? "新画像项")}</span><h3>{selected.proposalType === "create" ? "新增画像建议" : "画像更新建议"}</h3></div>{conflict ? <span className="claim-review__conflict"><AlertTriangle size={15} />与当前版本冲突，确认前请重新核对</span> : null}</header>
          <ClaimDiff current={selectedClaim?.currentVersion ?? null} proposal={selected} />
          <section className="claim-review__reason"><h4>为什么提出这条建议</h4><p>{selected.reason || "根据材料中的证据生成，请人工核对后决定。"}</p></section>
          <section className="claim-review__evidence">
            <header><h4>证据（{selected.evidence.length}）</h4><span><FileSearch size={14} />选择下方证据查看定位</span></header>
            {selected.evidence.map((evidence) => {
              const locator = formatEvidenceLocator(evidence.locator);
              return <button
                key={evidence.id}
                type="button"
                aria-label={`查看${locator}原文位置：${evidence.excerpt}`}
                onClick={() => onOpenEvidence(evidence)}
              >
                <span className="claim-review__evidence-locator">{locator}</span>
                <p>{evidence.excerpt}</p>
                <span className="claim-review__evidence-action" aria-hidden="true">查看原文位置<ArrowRight size={15} /></span>
              </button>;
            })}
          </section>
          {selected.status === "pending" ? <footer className="claim-review__actions">
            <label><input type="checkbox" checked={Boolean(pending[selected.id])} onChange={(event) => setPending((value) => event.target.checked ? { ...value, [selected.id]: { decision: "accepted", expectedVersion: selectedClaim?.version ?? 0 } } : Object.fromEntries(Object.entries(value).filter(([id]) => id !== selected.id)))} />加入批量处理</label>
            {pending[selected.id] ? <select aria-label="这条建议的批量决定" value={pending[selected.id].decision} onChange={(event) => setPending((value) => ({ ...value, [selected.id]: { ...value[selected.id], decision: event.target.value as ClaimDecision } }))}><option value="accepted">批量确认</option><option value="rejected">批量拒绝</option></select> : null}
            <Button variant="danger" loading={busy === selected.id} onClick={() => void decide(selected, "rejected", selectedClaim)}><XCircle size={16} />拒绝建议</Button>
            <Button loading={busy === selected.id} onClick={() => void decide(selected, "accepted", selectedClaim)}><CheckCircle2 size={16} />确认此项</Button>
          </footer> : null}
        </> : null}
      </main>
    </div>
    {Object.keys(pending).length ? <footer className="claim-review__batch"><span>已选择 <strong>{Object.keys(pending).length}</strong> 条；服务器确认前不会从列表移除。</span><Button loading={busy === "batch"} onClick={() => void submitBatch()}>批量确认</Button></footer> : null}
  </section>;
}
