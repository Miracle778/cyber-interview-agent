import type { QuestionCandidate } from "./reviewTypes";

export interface LogicalQuestionGroup {
  id: string;
  primary: QuestionCandidate;
  members: QuestionCandidate[];
  status: QuestionCandidate["status"];
  topics: string[];
}

export function canonicalQuestion(value: string) {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/^(请问|请解释一下|请简述|请说明)\s*/u, "")
    .replace(/[\p{P}\p{S}\s]+/gu, "");
}

export function groupLogicalQuestions(candidates: QuestionCandidate[]): LogicalQuestionGroup[] {
  const publishedByCanonical = new Map<string, string>();
  for (const candidate of candidates) {
    if (candidate.status === "published") {
      publishedByCanonical.set(canonicalQuestion(candidate.question.questionText), candidate.question.questionId);
    }
  }

  const buckets = new Map<string, QuestionCandidate[]>();
  for (const candidate of candidates) {
    const canonical = canonicalQuestion(candidate.question.questionText);
    const questionId = candidate.duplicateOfQuestionId
      ?? publishedByCanonical.get(canonical)
      ?? (candidate.status === "published" ? candidate.question.questionId : null);
    const key = questionId ? `question:${questionId}` : `canonical:${canonical || candidate.id}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(candidate);
    buckets.set(key, bucket);
  }

  return [...buckets.entries()].map(([id, unsorted]) => {
    const members = [...unsorted].sort((left, right) => {
      if (left.isActiveVersion && !right.isActiveVersion) return -1;
      if (right.isActiveVersion && !left.isActiveVersion) return 1;
      if (left.status === "published" && right.status !== "published") return -1;
      if (right.status === "published" && left.status !== "published") return 1;
      return right.updatedAt.localeCompare(left.updatedAt);
    });
    const primary = members[0];
    const status: QuestionCandidate["status"] = members.some((item) => item.status === "published")
      ? "published"
      : members.some((item) => item.status === "review_pending")
        ? "review_pending"
        : members.some((item) => item.status === "draft") ? "draft" : "rejected";
    return {
      id,
      primary,
      members,
      status,
      topics: [...new Set(members.flatMap((item) => item.question.topics))],
    };
  }).sort((left, right) => right.primary.updatedAt.localeCompare(left.primary.updatedAt));
}
