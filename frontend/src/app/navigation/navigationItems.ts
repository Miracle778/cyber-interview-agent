import { Activity, BookOpenText, BrainCircuit, BriefcaseBusiness, MessageSquareText, Settings, UserRound, type LucideIcon } from "lucide-react";

export interface NavigationItem {
  label: string;
  to: "/review" | "/knowledge" | "/profile" | "/targets" | "/retrospectives" | "/agents" | "/settings";
  icon: LucideIcon;
}

export interface NavigationGroup {
  label: string;
  items: NavigationItem[];
}

export const NAVIGATION_GROUPS: NavigationGroup[] = [
  {
    label: "工作台",
    items: [
      { label: "复习", to: "/review", icon: BrainCircuit },
      { label: "知识库", to: "/knowledge", icon: BookOpenText },
      { label: "个人画像", to: "/profile", icon: UserRound },
      { label: "求职目标", to: "/targets", icon: BriefcaseBusiness },
      { label: "面试复盘", to: "/retrospectives", icon: MessageSquareText },
      { label: "Agent 运行中心", to: "/agents", icon: Activity },
    ],
  },
  {
    label: "系统",
    items: [{ label: "设置", to: "/settings", icon: Settings }],
  },
];
