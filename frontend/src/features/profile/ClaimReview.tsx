import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronRight, FileSearch, RefreshCw, XCircle } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { Button } from "../../shared/ui/Button";
import { batchDecideClaimProposals, decideClaimProposal } from "./profileApi";
import type { ClaimDecision, ProfileClaimProposal, ProfileClaimReview, ProfileClaimWorkspace, ProfileEvidence } from "./profileTypes";
import { ClaimDiff } from "./ClaimDiff";
import { formatEvidenceLocator } from "./evidenceLocator";
import { profileClaimTypeLabel, userFacingClaimReason } from "./profilePresentation";

type PendingDecision = { decision: ClaimDecision; expectedVersion: number };

function proposalClaim(snapshot: ProfileClaimWorkspace, proposal: ProfileClaimProposal) {
  return snapshot.claims.find((claim) => claim.id === proposal.targetClaimId || claim.proposals.some((item) => item.id === proposal.id)) ?? null;
}

function proposalType(proposal: ProfileClaimProposal, claim: ProfileClaimReview | null) {
  const category = proposal.proposedValue.category;
  return claim?.claimType ?? (typeof category === "string" ? category : "new");
}

function proposalTitle(proposal: ProfileClaimProposal, claim: ProfileClaimReview | null) {
  const value = proposal.proposedValue;
  const type = proposalType(proposal, claim);
  const preferred = type === "experience"
    ? value.company ?? value.organization ?? value.role
    : type === "education"
      ? value.school ?? value.organization ?? value.major
      : value.name ?? value.title ?? value.skill ?? value.role ?? value.url;
  return typeof preferred === "string" && preferred.trim() ? preferred : profileClaimTypeLabel(type);
}

function statusLabel(status: string) {
  return ({ pending: "待确认", accepted: "已确认", rejected: "已忽略" } as Record<string, string>)[status] ?? status;
}

export function ClaimReview({ workspaceId, snapshot, loading = false, onRefresh, onOpenEvidence }: { workspaceId: string; snapshot: ProfileClaimWorkspace | null; loading?: boolean; onRefresh: () => Promise<unknown> | void; onOpenEvidence: (evidence: ProfileEvidence) => void }) {
  const [status, setStatus] = useState("pending");
  const [category, setCategory] = useState("all");
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, PendingDecision>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const proposals = snapshot?.proposals ?? [];
  const categories = useMemo(() => [...new Set([
    ...(snapshot?.claims ?? []).map((claim) => claim.claimType),
    ...proposals.map((proposal) => proposalType(proposal, snapshot ? proposalClaim(snapshot, proposal) : null)).filter((value) => value !== "new"),
  ])], [proposals, snapshot]);
  const filtered = proposals.filter((proposal) => {
    const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
    return (status === "all" || proposal.status === status) && (category === "all" || proposalType(proposal, claim) === category);
  });
  const selected = filtered.find((item) => item.id === selectedProposalId) ?? filtered[0] ?? null;
  const selectedClaim = selected && snapshot ? proposalClaim(snapshot, selected) : null;
  const conflict = selected && selectedClaim?.conflicts.some((item) => item.proposalId === selected.id);
  const filteredCountLabel = status === "pending"
    ? "条待确认"
    : status === "accepted"
      ? "条已确认"
      : status === "rejected"
        ? "条已忽略"
        : "条简历要点";

  async function decide(proposal: ProfileClaimProposal, decision: ClaimDecision, claim: ProfileClaimReview | null) {
    setBusy(proposal.id);
    setNotice(null);
    try {
      await decideClaimProposal(workspaceId, proposal.id, decision, claim?.version ?? 0);
      setPending((value) => { const next = { ...value }; delete next[proposal.id]; return next; });
      await onRefresh();
    } catch (error) {
      if (error instanceof ApiError && error.code.includes("conflict")) {
        setNotice("这条信息已经发生变化，页面已刷新；其他选择仍然保留。");
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
      if (result.items.some((item) => item.status === "conflict")) setNotice("部分信息已经发生变化，相关内容已刷新并保留选择，请重新核对。");
      await onRefresh();
    } catch (error) { setNotice(error instanceof Error ? error.message : "批量决定没有保存"); }
    finally { setBusy(null); }
  }

  if (loading) return <div className="profile-loading" role="status"><p>正在读取画像建议…</p></div>;

  return <section className="claim-review">
    <header className="claim-review__toolbar">
      <div><h2>确认简历要点</h2><p>系统从简历中整理出了这些技能和经历。请确认是否准确，确认后简历助手才能放心使用。</p></div>
    </header>
    <div className="claim-review__filters" aria-label="简历要点筛选">
      <label>状态<select aria-label="按状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="pending">待确认</option><option value="accepted">已确认</option><option value="rejected">已忽略</option><option value="all">全部</option></select></label>
      <label>分类<select aria-label="按分类筛选" value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部分类</option>{categories.map((item) => <option key={item} value={item}>{profileClaimTypeLabel(item)}</option>)}</select></label>
      <span><strong>{filtered.length}</strong> {filteredCountLabel}</span>
      <Button variant="ghost" size="sm" onClick={() => void onRefresh()}><RefreshCw size={15} />刷新</Button>
    </div>
    {notice ? <div className="claim-review__notice" role="status"><AlertTriangle size={17} />{notice}</div> : null}
    <div className="claim-review__workspace">
      <aside className="claim-review__queue" aria-label="待确认的简历要点">
        {filtered.length ? filtered.map((proposal) => {
          const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
          const hasConflict = claim?.conflicts.some((item) => item.proposalId === proposal.id);
          return <button key={proposal.id} type="button" aria-current={selected?.id === proposal.id} onClick={() => setSelectedProposalId(proposal.id)}>
            <span><em>{profileClaimTypeLabel(proposalType(proposal, claim))}</em><strong>{proposalTitle(proposal, claim)}</strong><small>{proposal.reason ? userFacingClaimReason(proposal.reason) : "根据简历原文整理"}</small></span>
            <span className={hasConflict ? "claim-review__badge claim-review__badge--warning" : "claim-review__badge"}>{hasConflict ? <><AlertTriangle size={13} />内容有变化</> : statusLabel(proposal.status)}</span><ChevronRight size={16} />
          </button>;
        }) : <div className="claim-review__empty"><CheckCircle2 size={24} /><strong>当前没有需要处理的内容</strong><p>可以切换状态或分类查看其他简历要点。</p></div>}
      </aside>
      <main className="claim-review__detail">
        {selected ? <>
          <header><div><span>{profileClaimTypeLabel(proposalType(selected, selectedClaim))}</span><h3>{proposalTitle(selected, selectedClaim)}</h3></div>{conflict ? <span className="claim-review__conflict"><AlertTriangle size={15} />这条信息与之前记录不同，请重新核对</span> : null}</header>
          <ClaimDiff current={selectedClaim?.currentVersion ?? null} proposal={selected} />
          <section className="claim-review__reason"><h4>系统为什么整理出这条信息</h4><p>{selected.reason ? userFacingClaimReason(selected.reason) : "这条信息来自你的简历原文，请核对后决定是否保留。"}</p></section>
          <section className="claim-review__evidence">
            <header><h4>来自简历（{selected.evidence.length} 处）</h4><span><FileSearch size={14} />点击可查看原文位置</span></header>
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
                <span className="claim-review__evidence-action" aria-hidden="true">查看原文<ArrowRight size={15} /></span>
              </button>;
            })}
          </section>
          {selected.status === "pending" ? <footer className="claim-review__actions">
            <label><input type="checkbox" checked={Boolean(pending[selected.id])} onChange={(event) => setPending((value) => event.target.checked ? { ...value, [selected.id]: { decision: "accepted", expectedVersion: selectedClaim?.version ?? 0 } } : Object.fromEntries(Object.entries(value).filter(([id]) => id !== selected.id)))} />稍后一起处理</label>
            {pending[selected.id] ? <select aria-label="这条信息的批量决定" value={pending[selected.id].decision} onChange={(event) => setPending((value) => ({ ...value, [selected.id]: { ...value[selected.id], decision: event.target.value as ClaimDecision } }))}><option value="accepted">确认准确</option><option value="rejected">不保留</option></select> : null}
            <Button variant="secondary" loading={busy === selected.id} onClick={() => void decide(selected, "rejected", selectedClaim)}><XCircle size={16} />不保留</Button>
            <Button loading={busy === selected.id} onClick={() => void decide(selected, "accepted", selectedClaim)}><CheckCircle2 size={16} />信息准确</Button>
          </footer> : null}
        </> : null}
      </main>
    </div>
    {Object.keys(pending).length ? <footer className="claim-review__batch"><span>已选择 <strong>{Object.keys(pending).length}</strong> 条，提交前仍可逐项修改。</span><Button loading={busy === "batch"} onClick={() => void submitBatch()}>提交所选结果</Button></footer> : null}
  </section>;
}
