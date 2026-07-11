import { BookOpenText, BrainCircuit, Settings, type LucideIcon } from "lucide-react";

export interface NavigationItem {
  label: string;
  to: "/review" | "/knowledge" | "/settings";
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
    ],
  },
  {
    label: "系统",
    items: [{ label: "设置", to: "/settings", icon: Settings }],
  },
];
