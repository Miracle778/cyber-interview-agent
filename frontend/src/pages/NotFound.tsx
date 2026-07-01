import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <main className="page-shell">
      <h1>页面不存在</h1>
      <p>你访问的页面尚未定义。</p>
      <Link className="text-link" to="/">
        返回首页
      </Link>
    </main>
  );
}

