export function DeepDiveSessionList({ sessions, activeId, onSelect }: { sessions: { id: string; title: string; subtitle: string }[]; activeId?: string; onSelect: (id: string) => void }) {
  return <nav className="deep-dive-session-list" aria-label="项目深挖会话"><h3>项目会话</h3>{sessions.map((session) => <button key={session.id} type="button" aria-current={session.id === activeId ? "page" : undefined} onClick={() => onSelect(session.id)}><strong>{session.title}</strong><small>{session.subtitle}</small></button>)}</nav>;
}
