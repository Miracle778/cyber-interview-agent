import { useState } from "react";
import { Archive, MessageSquarePlus, MessagesSquare, Search, Trash2 } from "lucide-react";
import { Button } from "../../shared/ui/Button";
import { parseApiTimestamp } from "../../shared/time";
import type { AgentSession } from "../agent/agentTypes";

function readableTitle(title: string) {
  return ["个人画像对话", "画像会话", "简历助手对话"].includes(title)
    || title.startsWith("当前画像快照：")
    || title.includes("（当前问题见本轮用户消息）")
    ? "画像助手对话"
    : title;
}

function readablePreview(content?: string | null) {
  const paragraph = (content ?? "")
    .split(/\n\s*\n/)
    .map((item) => item
      .replace(/^\s*(?:[-*#>|]+\s*)+/, "")
      .replace(/[#*_`>|]+/g, "")
      .replace(/\s+/g, " ")
      .trim())
    .find((item) => item && !/^[-:|\s]+$/.test(item)) ?? "";
  return paragraph.length > 72 ? `${paragraph.slice(0, 72)}…` : paragraph;
}

function formatUpdatedAt(value: string) {
  const date = parseApiTimestamp(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

interface ProfileSessionListProps {
  sessions: AgentSession[];
  archived: AgentSession[];
  loading: boolean;
  creating: boolean;
  mutatingId: string | null;
  showRecycleBin: boolean;
  onShowRecycleBin: (show: boolean) => void;
  onCreate: () => void;
  onOpen: (id: string) => void;
  onArchive: (id: string) => void;
  onRestore: (id: string) => void;
  onDeletePermanently: (id: string, title: string) => void;
}

export function ProfileSessionList({
  sessions,
  archived,
  loading,
  creating,
  mutatingId,
  showRecycleBin,
  onShowRecycleBin,
  onCreate,
  onOpen,
  onArchive,
  onRestore,
  onDeletePermanently,
}: ProfileSessionListProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "running" | "attention">("all");
  const source = showRecycleBin ? archived : sessions;
  const hasActiveFilter = !showRecycleBin && filter !== "all";
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = source.filter((session) => {
    const running = ["running", "cancelling", "waiting_for_input", "waiting_for_approval"].includes(session.status);
    const attention = ["failed", "interrupted"].includes(session.status);
    const matchesFilter = showRecycleBin || filter === "all" || (filter === "running" && running) || (filter === "attention" && attention);
    const searchable = `${readableTitle(session.title)} ${session.lastMessagePreview ?? ""}`.toLocaleLowerCase();
    return matchesFilter && searchable.includes(normalizedQuery);
  });
  return (
    <section className="profile-session-list" aria-label="画像助手会话记录">
      <header>
        <div>
          <span>画像助手</span>
          <h2>{showRecycleBin ? "已归档会话" : "会话记录"}</h2>
          <p>{showRecycleBin ? "恢复后可继续原来的对话。" : "每个会话保存自己的上下文、运行记录和待处理结果。"}</p>
        </div>
        {!showRecycleBin ? <Button loading={creating} onClick={onCreate}><MessageSquarePlus size={17} />新建会话</Button> : null}
      </header>
      <div className="profile-session-list__toolbar">
        <label><Search size={16} /><span className="sr-only">搜索会话</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题或最近消息" /></label>
        {!showRecycleBin ? <div className="profile-session-list__filters" aria-label="筛选会话">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>全部</button>
          <button type="button" aria-pressed={filter === "running"} onClick={() => setFilter("running")}>正在运行</button>
          <button type="button" aria-pressed={filter === "attention"} onClick={() => setFilter("attention")}>需要处理</button>
        </div> : null}
        <button type="button" aria-pressed={showRecycleBin} onClick={() => onShowRecycleBin(!showRecycleBin)}>
          {showRecycleBin ? <MessagesSquare size={16} /> : <Trash2 size={16} />}
          {showRecycleBin ? "返回会话记录" : `回收站${archived.length ? ` ${archived.length}` : ""}`}
        </button>
      </div>
      {loading ? <div className="profile-session-list__empty" role="status">正在读取会话记录…</div> : null}
      {!loading && !filtered.length ? (
        <div className="profile-session-list__empty">
          <MessagesSquare size={28} />
          <h3>{query || hasActiveFilter ? "没有匹配的会话" : showRecycleBin ? "回收站是空的" : "开始第一次画像对话"}</h3>
          {!query && !hasActiveFilter && !showRecycleBin ? <><p>你可以让画像助手检查资料完整性、梳理经历或准备自我介绍。</p><Button onClick={onCreate}>开始新对话</Button></> : null}
        </div>
      ) : null}
      <div className="profile-session-list__grid">
        {filtered.map((session) => {
          const running = ["running", "cancelling", "waiting_for_input", "waiting_for_approval"].includes(session.status);
          const needsAttention = ["failed", "interrupted"].includes(session.status);
          const preview = readablePreview(session.lastMessagePreview);
          return <article key={session.id}>
            <button className="profile-session-list__open" type="button" onClick={() => onOpen(session.id)}>
              <span><MessagesSquare size={18} /></span>
              <div><h3 title={readableTitle(session.title)}>{readableTitle(session.title)}</h3><p>{preview || `最近更新：${formatUpdatedAt(session.updatedAt)}`}</p></div>
              <small className={needsAttention ? "is-warning" : ""}>{running ? "正在运行" : needsAttention ? "需要处理" : showRecycleBin ? "已归档" : "可继续"}</small>
            </button>
            <footer>
              {showRecycleBin ? <>
                <button type="button" disabled={mutatingId === session.id} onClick={() => onRestore(session.id)}>恢复</button>
                <button className="is-danger" type="button" disabled={mutatingId === session.id} onClick={() => onDeletePermanently(session.id, readableTitle(session.title))}>永久删除</button>
              </> : <button type="button" disabled={running || mutatingId === session.id} title={running ? "请先停止当前任务" : "归档会话"} onClick={() => onArchive(session.id)}><Archive size={14} />归档</button>}
            </footer>
          </article>;
        })}
      </div>
    </section>
  );
}
