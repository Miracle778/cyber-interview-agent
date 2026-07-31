import { AlertTriangle, CheckCircle2, Clock3, LoaderCircle } from "lucide-react";
import { formatBeijingDateTime } from "../../shared/time";
import {
  evaluationStatusMeta,
  evaluationContractLabel,
  formatEvaluationVersion,
} from "./evaluationPresentation";
import type { EvaluationRun } from "./evaluationTypes";


export function EvaluationReportHeader({
  run,
  caseCount,
}: {
  run: EvaluationRun;
  caseCount?: number;
}) {
  const status = evaluationStatusMeta(run.status);
  const StatusIcon = status.tone === "success"
    ? CheckCircle2
    : status.tone === "danger"
      ? AlertTriangle
      : run.status === "running"
        ? LoaderCircle
        : Clock3;
  return (
    <header className="evaluation-report-header">
      <div>
        <span className="evaluation-report-header__eyebrow">
          {evaluationContractLabel(run)}
        </span>
        <h1>{formatEvaluationVersion(run)}</h1>
        <p>
          {formatBeijingDateTime(run.completedAt ?? run.createdAt) ?? "时间未知"}
          {caseCount !== undefined ? ` · ${caseCount} 个复测案例` : ""}
        </p>
      </div>
      <span className="evaluation-report-header__status" data-tone={status.tone}>
        <StatusIcon size={17} />
        {status.label}
      </span>
    </header>
  );
}
