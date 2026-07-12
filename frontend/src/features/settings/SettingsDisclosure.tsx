import { useEffect, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

interface SettingsDisclosureProps {
  id: string;
  title: string;
  description: string;
  defaultExpanded?: boolean;
  children: ReactNode;
}

export function SettingsDisclosure({ id, title, description, defaultExpanded = false, children }: SettingsDisclosureProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  useEffect(() => {
    if (defaultExpanded) setExpanded(true);
  }, [defaultExpanded]);

  const panelId = `${id}-panel`;
  return (
    <section className="settings-disclosure" aria-labelledby={`${id}-title`}>
      <button
        type="button"
        className="settings-disclosure__trigger"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>
          <span id={`${id}-title`} className="settings-disclosure__title">{title}</span>
          <span className="settings-disclosure__description">{description}</span>
        </span>
        <ChevronDown className="settings-disclosure__icon" aria-hidden="true" size={18} />
      </button>
      {expanded ? <div id={panelId} className="settings-disclosure__panel">{children}</div> : null}
    </section>
  );
}
