import { Lightbulb } from "lucide-react";
import type { ActionableProfileGap } from "./profileTypes";

export function ProfileActionableGaps({ gaps, onEdit }: { gaps: ActionableProfileGap[]; onEdit: (claimId: string) => void }) {
  if (!gaps.length) return null;
  return <section className="profile-gaps" aria-labelledby="profile-gaps-title">
    <header>
      <span><Lightbulb size={18} /></span>
      <div><h2 id="profile-gaps-title">让这些经历更有说服力</h2><p>补充关键做法或结果，后续生成简历和准备面试时会更具体。</p></div>
    </header>
    <ul>{gaps.slice(0, 5).map((gap) => <li key={`${gap.claimId}-${gap.field}`}>
      <span>{gap.message}</span>
      <button type="button" onClick={() => onEdit(gap.claimId)}>去补充</button>
    </li>)}</ul>
  </section>;
}
