import { useEffect, useRef, useState } from "react";
import { Menu, Sparkles, X } from "lucide-react";
import { useLocation } from "react-router-dom";
import { PrimaryNavigation } from "./PrimaryNavigation";

export function MobileNavigation() {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();

  function closeNavigation() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    setIsOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeNavigation();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <>
      <header className="mobile-header">
        <button
          ref={triggerRef}
          className="icon-button"
          type="button"
          aria-label="打开导航"
          aria-expanded={isOpen}
          onClick={() => setIsOpen(true)}
        >
          <Menu size={21} aria-hidden="true" />
        </button>
        <div className="mobile-header__brand">
          <Sparkles size={19} aria-hidden="true" />
          <span>Cyber Interview Agent</span>
        </div>
        <span className="mobile-header__spacer" aria-hidden="true" />
      </header>

      {isOpen ? (
        <div className="mobile-drawer-layer">
          <button
            className="mobile-drawer__backdrop"
            type="button"
            aria-label="关闭导航"
            onClick={closeNavigation}
          />
          <aside className="mobile-drawer" role="dialog" aria-modal="true" aria-label="主导航">
            <div className="mobile-drawer__header">
              <p className="mobile-drawer__title">Cyber Interview Agent</p>
              <button
                ref={closeRef}
                className="icon-button"
                type="button"
                aria-label="关闭导航"
                onClick={closeNavigation}
              >
                <X size={21} aria-hidden="true" />
              </button>
            </div>
            <PrimaryNavigation onNavigate={closeNavigation} />
          </aside>
        </div>
      ) : null}
    </>
  );
}
