import { useState } from "react";
import { Lightbulb } from "lucide-react";
import type { ActionableProfileGap } from "./profileTypes";

export function ProfileActionableGaps({ gaps, onEdit }: { gaps: ActionableProfileGap[]; onEdit: (claimId: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? gaps : gaps.slice(0, 2);
  return <section className="profile-gaps" aria-labelledby="profile-gaps-title">
    <header>
      <span><Lightbulb size={18} /></span>
      <div><h2 id="profile-gaps-title">待完善信息</h2><p>{gaps.length ? "补充关键做法或结果，让经历更有说服力。" : "暂时没有需要补充的关键信息。"}</p></div>
    </header>
    {gaps.length ? <><ul>{visible.map((gap) => <li key={`${gap.claimId}-${gap.field}`}>
      <span>{gap.message}</span>
      <button type="button" onClick={() => onEdit(gap.claimId)}>去补充</button>
    </li>)}</ul>{gaps.length > 2 ? <button className="profile-gaps__more" type="button" onClick={() => setExpanded((current) => !current)}>{expanded ? "收起" : `查看其余 ${gaps.length - 2} 项`}</button> : null}</> : <div className="profile-gaps__empty">画像中的关键经历目前都有基本说明。</div>}
  </section>;
}
