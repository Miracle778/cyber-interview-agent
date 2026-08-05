import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export type ReviewSection = "catalog" | "practice";

export function ReviewShell({ section, onSectionChange, actions, returnTo, returnLabel = "返回运行中心", children }: { section: ReviewSection; onSectionChange: (value: ReviewSection) => void; actions?: ReactNode; returnTo?: string | null; returnLabel?: string; children: ReactNode }) {
  return (
    <section className="review-shell">
      <header className="review-shell__toolbar">
        {returnTo ? (
          <Link className="review-run-center-return" to={returnTo}>
            <ArrowLeft size={16} aria-hidden="true" />
            {returnLabel}
          </Link>
        ) : null}
        <h1>复习</h1>
        <nav className="review-primary-tabs" aria-label="复习工作台入口">
          <button type="button" aria-current={section === "practice" ? "page" : undefined} onClick={() => onSectionChange("practice")}>开始复习</button>
          <button type="button" aria-current={section === "catalog" ? "page" : undefined} onClick={() => onSectionChange("catalog")}>题库整理</button>
        </nav>
        {actions ? <div className="review-shell__actions">{actions}</div> : null}
      </header>
      <div className="review-shell__content">{children}</div>
    </section>
  );
}
