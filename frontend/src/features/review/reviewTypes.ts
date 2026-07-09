export type ReviewMode = "weak-point" | "random-mixed" | "topic-focused" | "recent-mistake";
export type MasteryState = "unknown" | "weak" | "partial" | "stable" | "strong";

export interface ReviewQuestion {
  id: string;
  title: string;
  questionText: string;
  referenceAnswer: string;
  topics: string[];
  difficulty: "easy" | "medium" | "hard";
  keyPoints: string[];
  followUps: string[];
  mastery: MasteryState;
}
