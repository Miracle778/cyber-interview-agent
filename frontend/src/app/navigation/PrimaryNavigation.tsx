import type { MouseEvent } from "react";
import { NavLink } from "react-router-dom";
import { NAVIGATION_GROUPS } from "./navigationItems";

interface PrimaryNavigationProps {
  onNavigate?: () => void;
  activeAgentCount?: number;
}

export function PrimaryNavigation({
  onNavigate,
  activeAgentCount = 0,
}: PrimaryNavigationProps) {
  function handleNavigate(event: MouseEvent<HTMLAnchorElement>) {
    if (
      document.body.dataset.modelBindingsDirty === "true" &&
      !globalThis.confirm("模型配置还没有保存，确定离开吗？")
    ) {
      event.preventDefault();
      return;
    }
    onNavigate?.();
  }

  return (
    <nav className="primary-nav" aria-label="主导航">
      {NAVIGATION_GROUPS.map((group) => (
        <div className="primary-nav__group" key={group.label}>
          <p className="primary-nav__label">{group.label}</p>
          <ul className="primary-nav__list">
            {group.items.map((item) => {
              const Icon = item.icon;
              const isAgentCenter = item.to === "/agents";
              return (
                <li key={item.to}>
                  <NavLink
                    className={({ isActive }) =>
                      `primary-nav__link${isActive ? " primary-nav__link--active" : ""}`
                    }
                    to={isAgentCenter && activeAgentCount > 0
                      ? "/agents?status=running"
                      : item.to}
                    onClick={handleNavigate}
                    aria-label={isAgentCenter && activeAgentCount > 0
                      ? `${item.label}，${activeAgentCount} 个正在运行`
                      : undefined}
                  >
                    <Icon size={19} aria-hidden="true" />
                    <span>{item.label}</span>
                    {isAgentCenter && activeAgentCount > 0 ? (
                      <span className="primary-nav__badge" aria-hidden="true">
                        {activeAgentCount > 99 ? "99+" : activeAgentCount}
                      </span>
                    ) : null}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
