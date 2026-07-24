import { useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, FileSearch, RefreshCw, XCircle } from "lucide-react";
import { ApiError } from "../../shared/api/client";
import { Button } from "../../shared/ui/Button";
import { batchDecideClaimProposals, decideClaimProposal } from "./profileApi";
import type { ClaimDecision, ProfileClaimProposal, ProfileClaimReview, ProfileClaimWorkspace, ProfileEvidence } from "./profileTypes";
import { formatEvidenceLocator } from "./evidenceLocator";
import { ProfileBatchConfirmDialog } from "./ProfileBatchConfirmDialog";
import { ProfileProposalPreview } from "./ProfileProposalPreview";
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

function proposalSourceLabel(proposal: ProfileClaimProposal) {
  return ({
    resume_extraction: "来自简历",
    agent_inference: "根据经历归纳",
    conversation: "来自对话",
  } as Record<string, string>)[proposal.sourceKind ?? "resume_extraction"] ?? "个人资料建议";
}

function hasConflict(snapshot: ProfileClaimWorkspace | null, proposal: ProfileClaimProposal) {
  const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
  return Boolean(claim?.conflicts.some((item) => item.proposalId === proposal.id));
}

function isSafeToAccept(snapshot: ProfileClaimWorkspace | null, proposal: ProfileClaimProposal) {
  if (proposal.status !== "pending" || hasConflict(snapshot, proposal)) return false;
  if ((proposal.sourceKind ?? "resume_extraction") === "resume_extraction" && !proposal.evidence.length) return false;
  return Object.entries(proposal.proposedValue).some(([key, value]) => key !== "category" && value !== null && value !== "");
}

export function ClaimReview({ workspaceId, snapshot, loading = false, onRefresh, onOpenEvidence }: { workspaceId: string; snapshot: ProfileClaimWorkspace | null; loading?: boolean; onRefresh: () => Promise<unknown> | void; onOpenEvidence: (evidence: ProfileEvidence) => void }) {
  const [status, setStatus] = useState("pending");
  const [category, setCategory] = useState("all");
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, PendingDecision>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmSafeBatch, setConfirmSafeBatch] = useState(false);

  const proposals = snapshot?.proposals ?? [];
  const categories = useMemo(() => [...new Set([
    ...(snapshot?.claims ?? []).map((claim) => claim.claimType),
    ...proposals.map((proposal) => proposalType(proposal, snapshot ? proposalClaim(snapshot, proposal) : null)).filter((value) => value !== "new"),
  ])], [proposals, snapshot]);
  const filtered = proposals.filter((proposal) => {
    const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
    return (status === "all" || proposal.status === status) && (category === "all" || proposalType(proposal, claim) === category);
  });
  const selectable = filtered.filter((proposal) => proposal.status === "pending" && !hasConflict(snapshot, proposal));
  const safeFiltered = filtered.filter((proposal) => isSafeToAccept(snapshot, proposal));
  const selected = filtered.find((item) => item.id === selectedProposalId) ?? filtered[0] ?? null;
  const selectedClaim = selected && snapshot ? proposalClaim(snapshot, selected) : null;
  const conflict = Boolean(selected && hasConflict(snapshot, selected));
  const selectedCount = Object.keys(pending).length;
  const allCurrentSelected = selectable.length > 0 && selectable.every((proposal) => pending[proposal.id]);
  const filteredCountLabel = status === "pending"
    ? "条待确认"
    : status === "accepted"
      ? "条已确认"
      : status === "rejected"
        ? "条已忽略"
        : "条简历要点";

  function setSelected(proposal: ProfileClaimProposal, checked: boolean) {
    const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
    setPending((value) => {
      if (checked) return { ...value, [proposal.id]: { decision: "accepted", expectedVersion: claim?.version ?? 0 } };
      const next = { ...value };
      delete next[proposal.id];
      return next;
    });
  }

  function selectCurrentFilter() {
    if (allCurrentSelected) {
      const currentIds = new Set(selectable.map((item) => item.id));
      setPending((value) => Object.fromEntries(Object.entries(value).filter(([id]) => !currentIds.has(id))));
      return;
    }
    setPending((value) => {
      const next = { ...value };
      selectable.forEach((proposal) => {
        const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
        next[proposal.id] = { decision: "accepted", expectedVersion: claim?.version ?? 0 };
      });
      return next;
    });
  }

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

  async function submitEntries(entries: [string, PendingDecision][]) {
    if (!entries.length) return;
    setBusy("batch");
    setNotice(null);
    try {
      const result = await batchDecideClaimProposals(workspaceId, entries.map(([proposalId, item]) => ({ proposalId, ...item })));
      const completed = new Set(result.items.filter((item) => item.status === "completed").map((item) => item.proposalId));
      setPending((value) => Object.fromEntries(Object.entries(value).filter(([id]) => !completed.has(id))));
      const failedCount = result.items.length - completed.size;
      setNotice(failedCount ? `${completed.size} 条已保存，${failedCount} 条发生变化或保存失败，已保留供你重新核对。` : `${completed.size} 条信息已保存。`);
      await onRefresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "批量决定没有保存");
    } finally {
      setBusy(null);
      setConfirmSafeBatch(false);
    }
  }

  function submitSelected(decision: ClaimDecision) {
    const entries = Object.entries(pending).map(([id, item]) => [id, { ...item, decision }] as [string, PendingDecision]);
    void submitEntries(entries);
  }

  function submitSafeFiltered() {
    const entries = safeFiltered.map((proposal) => {
      const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
      return [proposal.id, { decision: "accepted" as const, expectedVersion: claim?.version ?? 0 }] as [string, PendingDecision];
    });
    void submitEntries(entries);
  }

  if (loading) return <div className="profile-loading" role="status"><p>正在读取待确认内容…</p></div>;

  return <section className="claim-review">
    <header className="claim-review__toolbar">
      <div><h2>待确认</h2><p>核对系统从简历或对话中整理的信息。确认后，它们才会进入你的个人画像。</p></div>
      {status === "pending" && filtered.length ? <Button size="sm" onClick={() => setConfirmSafeBatch(true)}>一键确认当前可靠信息</Button> : null}
    </header>
    <div className="claim-review__filters" aria-label="简历要点筛选">
      <label>状态<select aria-label="按状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="pending">待确认</option><option value="accepted">已确认</option><option value="rejected">已忽略</option><option value="all">全部</option></select></label>
      <label>分类<select aria-label="按分类筛选" value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部分类</option>{categories.map((item) => <option key={item} value={item}>{profileClaimTypeLabel(item)}</option>)}</select></label>
      {selectable.length ? <label className="claim-review__select-all"><input type="checkbox" checked={allCurrentSelected} onChange={selectCurrentFilter} />全选当前筛选</label> : null}
      <span><strong>{filtered.length}</strong> {filteredCountLabel}</span>
      <Button variant="ghost" size="sm" onClick={() => void onRefresh()}><RefreshCw size={15} />刷新</Button>
    </div>
    {notice ? <div className="claim-review__notice" role="status"><AlertTriangle size={17} />{notice}</div> : null}
    <div className={`claim-review__workspace${selectedProposalId ? " claim-review__workspace--detail" : ""}`}>
      <aside className="claim-review__queue" aria-label="待确认的个人资料">
        {filtered.length ? filtered.map((proposal) => {
          const claim = snapshot ? proposalClaim(snapshot, proposal) : null;
          const itemConflict = hasConflict(snapshot, proposal);
          return <article key={proposal.id} aria-current={selected?.id === proposal.id}>
            {proposal.status === "pending" ? <input
              type="checkbox"
              aria-label={`选择 ${proposalTitle(proposal, claim)}`}
              checked={Boolean(pending[proposal.id])}
              disabled={itemConflict}
              onChange={(event) => setSelected(proposal, event.target.checked)}
            /> : null}
            <button type="button" onClick={() => setSelectedProposalId(proposal.id)}>
              <span><em>{proposalSourceLabel(proposal)} · {profileClaimTypeLabel(proposalType(proposal, claim))}</em><strong>{proposalTitle(proposal, claim)}</strong><small>{proposal.reason ? userFacingClaimReason(proposal.reason) : "根据你的资料整理"}</small></span>
              <span className={itemConflict ? "claim-review__badge claim-review__badge--warning" : "claim-review__badge"}>{itemConflict ? <><AlertTriangle size={13} />需要核对</> : statusLabel(proposal.status)}</span><ChevronRight size={16} />
            </button>
          </article>;
        }) : <div className="claim-review__empty"><CheckCircle2 size={24} /><strong>当前没有需要处理的内容</strong><p>系统新发现的信息会先放在这里，由你决定是否加入个人画像。</p></div>}
      </aside>
      <main className="claim-review__detail">
        {selected ? <>
          <header><button type="button" className="claim-review__mobile-back" aria-label="返回待确认列表" onClick={() => setSelectedProposalId(null)}><ArrowLeft size={17} /></button><div><span>{profileClaimTypeLabel(proposalType(selected, selectedClaim))}</span><h3>{proposalTitle(selected, selectedClaim)}</h3></div>{conflict ? <span className="claim-review__conflict"><AlertTriangle size={15} />这条信息与之前记录不同，请逐项核对</span> : null}</header>
          <div className="claim-review__detail-scroll">
            <ProfileProposalPreview current={selectedClaim?.currentVersion ?? null} proposal={selected} />
            <section className="claim-review__reason"><h4>为什么建议加入</h4><p>{selected.reason ? userFacingClaimReason(selected.reason) : "这条信息来自你的资料，请核对后决定是否保留。"}</p></section>
            {selected.evidence.length ? <section className="claim-review__evidence">
              <header><h4>来自简历（{selected.evidence.length} 处）</h4><span><FileSearch size={14} />可定位到完整简历</span></header>
              {selected.evidence.map((evidence) => {
                const locator = formatEvidenceLocator(evidence.locator);
                return <button key={evidence.id} type="button" aria-label={`查看${locator}原文位置：${evidence.excerpt}`} onClick={() => onOpenEvidence(evidence)}>
                  <span className="claim-review__evidence-locator">{locator}</span>
                  <p>{evidence.excerpt}</p>
                  <span className="claim-review__evidence-action" aria-hidden="true">查看原文<ArrowRight size={15} /></span>
                </button>;
              })}
            </section> : <section className="claim-review__reason"><h4>信息来自哪里</h4><p>{selected.sourceKind === "conversation" ? "来自你在画像助手中的明确描述。确认前不会加入个人画像。" : "这是系统根据已确认经历归纳出的建议，确认前不会加入个人画像。"}</p></section>}
          </div>
          {selected.status === "pending" ? <footer className="claim-review__actions">
            <Button variant="secondary" loading={busy === selected.id} onClick={() => void decide(selected, "rejected", selectedClaim)}><XCircle size={16} />不保留</Button>
            <Button loading={busy === selected.id} onClick={() => void decide(selected, "accepted", selectedClaim)}><CheckCircle2 size={16} />信息准确</Button>
          </footer> : null}
        </> : null}
      </main>
    </div>
    {selectedCount ? <footer className="claim-review__batch">
      <span>已选择 <strong>{selectedCount}</strong> 条，可统一确认或忽略。</span>
      <div><Button variant="ghost" onClick={() => setPending({})}>清空选择</Button><Button variant="secondary" loading={busy === "batch"} onClick={() => submitSelected("rejected")}>批量不保留</Button><Button loading={busy === "batch"} onClick={() => submitSelected("accepted")}>批量确认</Button></div>
    </footer> : null}
    {confirmSafeBatch ? <ProfileBatchConfirmDialog acceptedCount={safeFiltered.length} excludedCount={filtered.length - safeFiltered.length} busy={busy === "batch"} onCancel={() => setConfirmSafeBatch(false)} onConfirm={submitSafeFiltered} /> : null}
  </section>;
}
