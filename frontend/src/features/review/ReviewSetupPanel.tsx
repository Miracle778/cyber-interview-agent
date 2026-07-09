export function ReviewSetupPanel() {
  return (
    <section aria-label="复习设置">
      <h2>复习设置</h2>
      <label>
        题量
        <input defaultValue="10" inputMode="numeric" />
      </label>
      <label>
        模式
        <select defaultValue="weak-point">
          <option value="weak-point">薄弱点优先</option>
          <option value="random-mixed">随机混合</option>
          <option value="topic-focused">单主题巩固</option>
          <option value="recent-mistake">最近错误复现</option>
        </select>
      </label>
    </section>
  );
}
