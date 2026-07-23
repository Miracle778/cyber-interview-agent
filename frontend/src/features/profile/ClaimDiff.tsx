import type { ProfileClaimProposal, ProfileClaimVersion } from "./profileTypes";

function rows(value: Record<string, unknown> | null) {
  if (!value) return [];
  return Object.entries(value).map(([key, item]) => ({
    key,
    value: Array.isArray(item) ? item.join("、") : item && typeof item === "object" ? JSON.stringify(item) : String(item ?? "—"),
  }));
}

export function ClaimDiff({ current, proposal }: { current: ProfileClaimVersion | null; proposal: ProfileClaimProposal }) {
  const currentRows = new Map(rows(current?.value ?? null).map((item) => [item.key, item.value]));
  const proposedRows = new Map(rows(proposal.proposedValue).map((item) => [item.key, item.value]));
  const keys = [...new Set([...currentRows.keys(), ...proposedRows.keys()])];

  return <section className="claim-diff" aria-label="当前内容与建议内容对比">
    <header><span>字段</span><strong>当前内容</strong><strong>建议内容</strong></header>
    {keys.map((key) => {
      const before = currentRows.get(key) ?? "—";
      const after = proposedRows.get(key) ?? "—";
      const changed = before !== after;
      return <div key={key} data-changed={changed || undefined}><span>{key}</span><p>{before}</p><p>{after}</p></div>;
    })}
  </section>;
}
