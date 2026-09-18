import { useId, type ReactNode } from "react";

interface PanelProps {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  tone?: "default" | "danger" | "ok" | "warn";
}

// A labelled control-board panel (a section, not a generic card) with a rail
// accent, section eyebrow and optional header actions.
export default function Panel({
  title,
  eyebrow,
  actions,
  children,
  className = "",
  tone = "default",
}: PanelProps) {
  const headingId = useId();
  return (
    <section
      className={`panel panel--${tone} ${className}`.trim()}
      aria-labelledby={headingId}
    >
      <header className="panel__header">
        <div className="panel__heading">
          {eyebrow ? <p className="panel__eyebrow">{eyebrow}</p> : null}
          <h2 className="panel__title" id={headingId}>
            {title}
          </h2>
        </div>
        {actions ? <div className="panel__actions">{actions}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  );
}
