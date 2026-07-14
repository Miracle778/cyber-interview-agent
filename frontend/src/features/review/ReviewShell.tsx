import { BookMarked, GraduationCap } from "lucide-react";
import type { ReactNode } from "react";

export type ReviewSection = "catalog" | "practice";

export function ReviewShell({ section, onSectionChange, children }: { section: ReviewSection; onSectionChange: (value: ReviewSection) => void; children: ReactNode }) {
  return (
    <section className="review-shell">
      <nav className="review-primary-tabs" aria-label="复习工作台入口">
        <button type="button" aria-current={section === "catalog" ? "page" : undefined} onClick={() => onSectionChange("catalog")}><BookMarked size={18} /><span><strong>题库整理</strong><small>导入、纠错、分类与确认</small></span></button>
        <button type="button" aria-current={section === "practice" ? "page" : undefined} onClick={() => onSectionChange("practice")}><GraduationCap size={18} /><span><strong>开始复习</strong><small>选题、回答、追问与报告</small></span></button>
      </nav>
      {children}
    </section>
  );
}
