import { NavLink } from "react-router-dom";
import { NAVIGATION_GROUPS } from "./navigationItems";

interface PrimaryNavigationProps {
  onNavigate?: () => void;
}

export function PrimaryNavigation({ onNavigate }: PrimaryNavigationProps) {
  return (
    <nav className="primary-nav" aria-label="主导航">
      {NAVIGATION_GROUPS.map((group) => (
        <div className="primary-nav__group" key={group.label}>
          <p className="primary-nav__label">{group.label}</p>
          <ul className="primary-nav__list">
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <NavLink
                    className={({ isActive }) =>
                      `primary-nav__link${isActive ? " primary-nav__link--active" : ""}`
                    }
                    to={item.to}
                    onClick={onNavigate}
                  >
                    <Icon size={19} aria-hidden="true" />
                    <span>{item.label}</span>
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
