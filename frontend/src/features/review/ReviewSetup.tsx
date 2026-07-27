import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck, ChevronDown, ChevronUp, Play, Search, SlidersHorizontal, TriangleAlert, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { Card } from "../../shared/ui/Card";
import { getWorkspaceModelBindings, listProviders } from "../settings/settingsApi";
import type { WorkspaceConfig } from "../settings/settingsApi";
import type { ActiveQuestion, CreateReviewRoundRequest, Difficulty, ReviewMode } from "./reviewTypes";

const TOPIC_PREVIEW_LIMIT = 18;
const TOPIC_SEARCH_LIMIT = 40;

export function ReviewSetup({ workspace, questions, onCreate, onCatalog, busy }: { workspace: WorkspaceConfig; questions: ActiveQuestion[]; onCreate: (request: CreateReviewRoundRequest) => void; onCatalog: () => void; busy: boolean }) {
  const providers = useQuery({ queryKey: ["providers"], queryFn: listProviders });
  const bindings = useQuery({ queryKey: ["model-bindings", workspace.id], queryFn: () => getWorkspaceModelBindings(workspace.id) });
  const models = useMemo(() => (providers.data ?? []).flatMap((provider) => provider.enabled ? provider.models.filter((model) => model.enabled).map((model) => ({ id: model.id, label: `${provider.name} / ${model.displayName}` })) : []), [providers.data]);
  const topics = useMemo(() => [...new Set(questions.flatMap((item) => item.topics))].sort(), [questions]);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [topicQuery, setTopicQuery] = useState("");
  const [topicsExpanded, setTopicsExpanded] = useState(false);
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [mode, setMode] = useState<ReviewMode>("random-mixed");
  const [count, setCount] = useState(10);
  const [reasoning, setReasoning] = useState<CreateReviewRoundRequest["reasoningEffort"]>("none");
  const defaultModel = bindings.data?.bindings.answer_evaluation ?? models[0]?.id ?? "";
  const [selectedModel, setSelectedModel] = useState("");
  const effectiveModel = selectedModel || defaultModel;
  const available = questions.filter((item) => (selectedTopics.length === 0 || item.topics.some((topic) => selectedTopics.includes(topic))) && item.difficulty === difficulty).length;
  const matchingTopics = useMemo(() => {
    const normalizedQuery = topicQuery.trim().toLocaleLowerCase();
    const filtered = normalizedQuery
      ? topics.filter((topic) => topic.toLocaleLowerCase().includes(normalizedQuery))
      : topics;
    const selected = filtered.filter((topic) => selectedTopics.includes(topic));
    const unselected = filtered.filter((topic) => !selectedTopics.includes(topic));
    const ordered = [...selected, ...unselected];
    if (normalizedQuery) return ordered.slice(0, TOPIC_SEARCH_LIMIT);
    if (topicsExpanded) return ordered;
    return ordered.slice(0, Math.max(TOPIC_PREVIEW_LIMIT, selected.length));
  }, [selectedTopics, topicQuery, topics, topicsExpanded]);
  const hiddenTopicCount = topicQuery.trim()
    ? Math.max(0, topics.filter((topic) => topic.toLocaleLowerCase().includes(topicQuery.trim().toLocaleLowerCase())).length - matchingTopics.length)
    : Math.max(0, topics.length - matchingTopics.length);
  const topicRequired = mode === "topic-focused" && selectedTopics.length === 0;

  return (
    <Card title="创建复习轮次" icon={<SlidersHorizontal size={18} />}>
      <div className="review-setup-grid">
        <label className="field"><span className="field__label">复习模式</span><select className="field__input" value={mode} onChange={(event) => setMode(event.target.value as ReviewMode)}><option value="random-mixed">随机混合</option><option value="weak-point">薄弱优先</option><option value="topic-focused">专题复习</option><option value="recent-mistake">最近错题</option></select></label>
        <label className="field"><span className="field__label">难度</span><select className="field__input" value={difficulty} onChange={(event) => setDifficulty(event.target.value as Difficulty)}><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select></label>
        <label className="field"><span className="field__label">题量</span><input className="field__input" type="number" min={1} max={50} value={count} onChange={(event) => setCount(Number(event.target.value))} /></label>
        <label className="field"><span className="field__label">回答评价模型</span><select className="field__input" value={effectiveModel} onChange={(event) => setSelectedModel(event.target.value)}><option value="">请选择模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label>
        <label className="field"><span className="field__label">思考强度</span><select className="field__input" value={reasoning} onChange={(event) => setReasoning(event.target.value as CreateReviewRoundRequest["reasoningEffort"])}><option value="none">默认</option><option value="low">低</option><option value="medium">中</option><option value="high">高</option></select></label>
      </div>
      <fieldset className="topic-picker">
        <legend>复习主题</legend>
        <div className="topic-picker__toolbar">
          <label className="topic-picker__search">
            <Search size={16} aria-hidden="true" />
            <input aria-label="搜索复习主题" value={topicQuery} onChange={(event) => setTopicQuery(event.target.value)} placeholder="搜索主题" />
            {topicQuery ? <button type="button" aria-label="清空主题搜索" onClick={() => setTopicQuery("")}><X size={15} /></button> : null}
          </label>
          <span>{selectedTopics.length ? `已选 ${selectedTopics.length} 个` : "不选则从全部题目中出题"}</span>
          {selectedTopics.length ? <button type="button" className="topic-picker__clear" onClick={() => setSelectedTopics([])}>清空已选</button> : null}
        </div>
        <div className="topic-picker__options">
          {matchingTopics.map((topic) => <label key={topic}><input type="checkbox" checked={selectedTopics.includes(topic)} onChange={() => setSelectedTopics((current) => current.includes(topic) ? current.filter((item) => item !== topic) : [...current, topic])} />{topic}</label>)}
          {matchingTopics.length === 0 ? <p>没有匹配的主题</p> : null}
        </div>
        <div className="topic-picker__footer">
          {topicQuery.trim() ? <small>找到 {matchingTopics.length + hiddenTopicCount} 个主题{hiddenTopicCount ? `，当前显示前 ${matchingTopics.length} 个` : ""}</small> : <small>共 {topics.length} 个主题，默认紧凑展示 {Math.min(TOPIC_PREVIEW_LIMIT, topics.length)} 个</small>}
          {!topicQuery.trim() && topics.length > TOPIC_PREVIEW_LIMIT ? <button type="button" onClick={() => setTopicsExpanded((current) => !current)}>{topicsExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}{topicsExpanded ? "收起主题" : `展开全部（${topics.length}）`}</button> : null}
        </div>
      </fieldset>
      <div className="review-setup-summary"><span>匹配题目 {available} 道</span><span>本轮计划 {count} 道</span></div>
      <Button loading={busy} disabled={!effectiveModel || available < count || count < 1 || count > 50 || topicRequired} onClick={() => onCreate({ workspaceId: workspace.id, selectedTopics, difficulties: [difficulty], mode, questionCount: count, allowFollowUp: true, answerModelId: effectiveModel, reasoningEffort: reasoning })}><Play size={16} />开始复习</Button>
      {topicRequired ? <p className="field__hint field__hint--error">专题复习需要至少选择一个主题。</p> : null}
      {available < count ? <section className="review-readiness review-readiness--low review-readiness--compact" role="status"><span className="review-readiness__icon"><TriangleAlert size={20} /></span><div><h3>当前筛选题量不足</h3><p>可调整难度或题量，也可以先确认更多题目后再创建轮次。</p></div><Button variant="secondary" onClick={onCatalog}><BookOpenCheck size={16} />去题库整理</Button></section> : null}
    </Card>
  );
}
