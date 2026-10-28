import { useEffect, useState } from "react";
import { api, post, roleNames, type Entity } from "./api";
import { AppContext, Badge, Button, Icon, Loading } from "./ui";
import {
  AuditPage,
  Dashboard,
  KnowledgePage,
  RecordsPage,
  ReviewQueue,
  SystemPage,
} from "./overview";
import RecordDetail from "./record";
import { CaseLibrary } from "./cases";
import { DataReadinessPage } from "./provenance";

const navigation = [
  ["dashboard", "home", "工作台"],
  ["records", "record", "文物病历"],
  ["knowledge", "book", "循证资料"],
  ["cases", "book", "保护病例库"],
  ["data", "image", "数据来源与缺口"],
  ["consultations", "people", "专家会诊"],
  ["audit", "audit", "审计日志"],
];
function Login({ onLogin }: { onLogin: (user: Entity) => void }) {
  const [username, setUsername] = useState("surveyor"),
    [password, setPassword] = useState("ahr-demo-2026"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await post("/auth/login", { username, password });
      onLogin(data.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-story">
        <div className="brand">
          <span className="brand-seal">文</span>
          <div>
            文物病历<small>ARTIFACT HEALTH RECORD</small>
          </div>
        </div>
        <div className="login-story-copy">
          <span className="eyebrow">让每一次保护，都有据可循</span>
          <h1>
            记录时间的痕迹，
            <br />
            守护文明的延续。
          </h1>
          <p>
            从一张现状照片，到一份可追溯的修复档案。
            <br />
            连接现场调查、循证诊断与专家会诊。
          </p>
          <div className="login-workflow">
            <span>现状采集</span>
            <i>·</i>
            <span>病害标注</span>
            <i>·</i>
            <span>循证方案</span>
            <i>·</i>
            <span>长期档案</span>
          </div>
        </div>
        <div className="login-art" aria-hidden="true">
          <div className="art-ring ring-one" />
          <div className="art-ring ring-two" />
          <div className="art-ring ring-three" />
          <span>
            守 正<br />留 真
          </span>
        </div>
        <p className="login-note">辅助保护决策 · 人工确认与专家审核</p>
      </div>
      <div className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <span className="eyebrow">WELCOME TO THE WORKBENCH</span>
          <h2>进入保护工作台</h2>
          <p>选择工作身份，开始一次有记录的保护。</p>
          <label className="field">
            <span className="field-label">工作身份</span>
            <select
              value={
                Object.keys(roleNames).includes(username) ? username : "custom"
              }
              onChange={(e) =>
                setUsername(e.target.value === "custom" ? "" : e.target.value)
              }
            >
              {Object.entries(roleNames).map(([key, name]) => (
                <option key={key} value={key}>
                  {name} · {key}
                </option>
              ))}
              <option value="custom">其他账号</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              required
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field-label">登录密码</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <div className="callout compact">
            本地演示账号默认密码已填入。自定义部署请使用启动时生成的访问密码。
          </div>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <Button type="submit" variant="primary full" busy={busy} icon="arrow">
            进入工作台
          </Button>
          <small className="muted">
            病历与影像按角色授权访问；生成、修订、审核和导出均留痕。
          </small>
        </form>
      </div>
    </main>
  );
}
export default function App() {
  const [user, setUser] = useState<Entity | null>(null),
    [checking, setChecking] = useState(true),
    [dict, setDict] = useState<Entity>({}),
    [route, setRoute] = useState(location.hash.slice(1) || "dashboard"),
    [mobile, setMobile] = useState(false),
    [toasts, setToasts] = useState<Entity[]>([]);
  const notify = (
    message: string,
    kind: "success" | "error" | "info" = "success",
  ) => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items.slice(-2), { id, message, kind }]);
    setTimeout(
      () => setToasts((items) => items.filter((i) => i.id !== id)),
      kind === "error" ? 14000 : 4500,
    );
  };
  useEffect(() => {
    api("/auth/me")
      .then((data) => setUser(data.user || data))
      .catch(() => {})
      .finally(() => setChecking(false));
    const handle = () => {
      setRoute(location.hash.slice(1) || "dashboard");
      setMobile(false);
      window.scrollTo(0, 0);
    };
    const unauthorized = () => setUser(null);
    window.addEventListener("hashchange", handle);
    window.addEventListener("ahr:unauthorized", unauthorized);
    return () => {
      window.removeEventListener("hashchange", handle);
      window.removeEventListener("ahr:unauthorized", unauthorized);
    };
  }, []);
  useEffect(() => {
    if (user)
      api("/dictionary")
        .then(setDict)
        .catch((e) => notify(e.message, "error"));
  }, [user]);
  if (checking) return <Loading />;
  if (!user) return <Login onLogin={setUser} />;
  const page = route.split("/")[0],
    recordId = route.startsWith("records/")
      ? route.split("/")[1].split("?")[0]
      : null;
  const titles: Record<string, string> = {
    dashboard: "工作台",
    records: "文物病历",
    knowledge: "循证资料",
    cases: "保护病例库",
    data: "数据来源与缺口",
    consultations: "专家会诊",
    audit: "审计日志",
    system: "运行状态",
  };
  return (
    <AppContext.Provider value={{ user, dict, notify }}>
      <div className="app-shell">
        <aside className={`sidebar ${mobile ? "open" : ""}`}>
          <a href="#dashboard" className="brand">
            <span className="brand-seal">文</span>
            <div>
              文物病历<small>ARTIFACT HEALTH RECORD</small>
            </div>
          </a>
          <div className="sidebar-caption">保护工作空间</div>
          <nav>
            {navigation.map(([key, icon, label]) => (
              <a
                className={`nav-link ${page === key ? "active" : ""}`}
                href={`#${key}`}
                key={key}
              >
                <Icon name={icon} />
                <span>{label}</span>
                {page === key && <span className="nav-dot" />}
              </a>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="sidebar-message">
              <span className="tiny-seal">循证</span>
              <b>每一步，留有依据</b>
              <p>
                保护原始记录
                <br />
                让专业判断可追溯
              </p>
            </div>
            <a
              href="#system"
              className={`nav-link ${page === "system" ? "active" : ""}`}
            >
              <Icon name="settings" />
              <span>运行状态</span>
            </a>
            <button
              className="nav-link logout"
              onClick={async () => {
                try {
                  await post("/auth/logout");
                  setUser(null);
                } catch (e) {
                  notify((e as Error).message, "error");
                }
              }}
            >
              <Icon name="logout" />
              <span>切换身份 / 退出</span>
            </button>
          </div>
        </aside>
        {mobile && (
          <button
            aria-label="关闭导航"
            className="sidebar-overlay"
            onClick={() => setMobile(false)}
          />
        )}
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumb">
              <button
                className="icon-button mobile-menu"
                onClick={() => setMobile(!mobile)}
                aria-label="展开导航"
              >
                ☰
              </button>
              <span>文物保护协作平台</span>
              <i>/</i>
              <b>{titles[page] || "工作台"}</b>
              {recordId && (
                <>
                  <i>/</i>
                  <b>病历详情</b>
                </>
              )}
            </div>
            <div className="topbar-user">
              <Badge value="neutral">本地工作空间</Badge>
              <span className="user-avatar">
                {user.name?.slice(-2) || "文保"}
              </span>
              <div>
                <b>{user.name || user.username}</b>
                <small>{roleNames[user.role] || user.role}</small>
              </div>
            </div>
          </header>
          <main className="content">
            {recordId ? (
              <RecordDetail key={recordId} id={recordId} />
            ) : page === "records" ? (
              <RecordsPage />
            ) : page === "cases" ? (
              <CaseLibrary />
            ) : page === "data" ? (
              <DataReadinessPage />
            ) : page === "knowledge" ? (
              <KnowledgePage />
            ) : page === "consultations" ? (
              <ReviewQueue />
            ) : page === "audit" ? (
              <AuditPage />
            ) : page === "system" ? (
              <SystemPage />
            ) : (
              <Dashboard />
            )}
          </main>
          <footer className="footer">
            <span>文物病历 · Artifact Health Record</span>
            <span>原始记录 / 循证决策 / 全程留痕</span>
          </footer>
        </div>
      </div>
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div
            className={`toast ${toast.kind}`}
            role={toast.kind === "error" ? "alert" : "status"}
            key={toast.id}
          >
            <Icon name={toast.kind === "error" ? "warning" : "check"} />
            <span>{toast.message}</span>
            <button
              className="icon-button"
              onClick={() =>
                setToasts((items) => items.filter((i) => i.id !== toast.id))
              }
              aria-label="关闭消息"
            >
              <Icon name="close" size={16} />
            </button>
          </div>
        ))}
      </div>
    </AppContext.Provider>
  );
}
