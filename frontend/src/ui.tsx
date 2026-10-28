import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useId,
  Children,
  isValidElement,
  cloneElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { api, type Entity, statusNames } from "./api";

export const AppContext = createContext<{
  user: Entity;
  dict: Entity;
  notify: (message: string, kind?: "success" | "error" | "info") => void;
}>({ user: {}, dict: {}, notify: () => {} });
export const useApp = () => useContext(AppContext);
export function useLoad<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    if (!path) {
      setLoading(false);
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    api<T>(path)
      .then((value) => {
        if (active) setData(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [path, revision]);
  return { data, setData, loading, error, reload };
}
export function useAction() {
  const { notify } = useApp();
  const [busy, setBusy] = useState(false);
  const act = async <T,>(
    fn: () => Promise<T>,
    message?: string,
  ): Promise<T | undefined> => {
    setBusy(true);
    try {
      const result = await fn();
      if (message) notify(message);
      return result;
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e), "error");
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { act, busy };
}
export function Icon({
  name,
  size = 20,
  ...props
}: {
  name: string;
  size?: number;
  [key: string]: any;
}) {
  const paths: Record<string, ReactNode> = {
    home: (
      <>
        <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z" />
        <path d="M9 21v-8h6v8" />
      </>
    ),
    record: (
      <>
        <path d="M7 3h10l4 4v14H7Z" />
        <path d="M17 3v5h4M11 12h6M11 16h6M3 7v14" />
      </>
    ),
    book: (
      <>
        <path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Z" />
        <path d="M12 5v15" />
      </>
    ),
    people: (
      <>
        <circle cx="9" cy="7" r="3" />
        <path d="M3 20v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M21 20v-3a6 6 0 0 0-4-5" />
      </>
    ),
    audit: (
      <>
        <path d="M12 3 3 6v6c0 5 9 9 9 9s9-4 9-9V6Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-6-6 6 6-6 6" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 5 5" />
      </>
    ),
    image: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="3" />
        <circle cx="8" cy="8" r="1.5" />
        <path d="m3 17 6-6 4 4 3-3 5 5" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" />
      </>
    ),
    close: <path d="m6 6 12 12M18 6 6 18" />,
    check: <path d="m5 12 4 4L19 6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    warning: (
      <>
        <path d="m12 3 10 18H2Z" />
        <path d="M12 9v5m0 3v.5" />
      </>
    ),
    logout: (
      <>
        <path d="M9 3H3v18h6M9 12h12m-5-5 5 5-5 5" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2" />
      </>
    ),
    external: (
      <>
        <path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7" />
      </>
    ),
    polygon: (
      <>
        <path d="m4 5 14-2 3 14-13 4Z" />
        <circle cx="4" cy="5" r="1" />
        <circle cx="18" cy="3" r="1" />
        <circle cx="21" cy="17" r="1" />
        <circle cx="8" cy="21" r="1" />
      </>
    ),
    ruler: (
      <>
        <path d="m3 17 14-14 4 4L7 21Z" />
        <path d="m8 12 2 2m2-6 2 2m2-6 2 2" />
      </>
    ),
    undo: (
      <>
        <path d="M8 5 3 10l5 5M3 10h11a6 6 0 0 1 6 6v3" />
      </>
    ),
    trash: (
      <>
        <path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7" />
      </>
    ),
    spark: (
      <>
        <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name] || paths.record}
    </svg>
  );
}
export function Button({
  children,
  variant = "",
  busy = false,
  icon,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: string;
  busy?: boolean;
  icon?: string;
}) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={`button ${variant} ${props.className || ""}`}
    >
      {busy ? (
        <span className="spinner small" />
      ) : icon ? (
        <Icon name={icon} size={17} />
      ) : null}
      {children}
    </button>
  );
}
export function Badge({
  value,
  children,
}: {
  value?: any;
  children?: ReactNode;
}) {
  return (
    <span
      className={`badge ${["approved", "pass", "ready", "available", "completed"].includes(value) ? "green" : ["warn", "review", "pending", "draft", "template_fallback", "queued"].includes(value) ? "amber" : ["block", "rejected", "failed", "error"].includes(value) ? "red" : "neutral"}`}
    >
      {children || statusNames[value] || value || "未记录"}
    </span>
  );
}
export function Empty({
  title = "暂无记录",
  description,
  action,
  icon = "record",
}: {
  title?: string;
  description?: string;
  action?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function Loading() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      <span>
        {slow
          ? "读取时间较长，请检查网络或服务状态；数据返回后会自动更新。"
          : "正在读取工作台数据…"}
      </span>
    </div>
  );
}
export function LoadState({
  loading,
  error,
  retry,
  children,
}: {
  loading: boolean;
  error: string;
  retry?: () => void;
  children: ReactNode;
}) {
  return loading ? (
    <Loading />
  ) : error ? (
    <div className="callout danger" role="alert">
      <Icon name="warning" />
      <div>
        <b>数据读取失败</b>
        <p>{error}</p>
        {retry && <Button onClick={retry}>重试</Button>}
      </div>
    </div>
  ) : (
    <>{children}</>
  );
}
export function Field({
  label,
  hint,
  children,
  wide = false,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const labelId = useId();
  const fields = Children.map(children, (child) => {
    if (
      !isValidElement(child) ||
      !["input", "select", "textarea"].includes(String(child.type))
    )
      return child;
    const control = child as ReactElement<{
      "aria-label"?: string;
      "aria-labelledby"?: string;
    }>;
    if (control.props["aria-label"] || control.props["aria-labelledby"])
      return child;
    return cloneElement(control, { "aria-labelledby": labelId });
  });
  return (
    <label className={`field ${wide ? "wide" : ""}`}>
      <span className="field-label" id={labelId}>
        {label}
      </span>
      {fields}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Panel({
  title,
  eyebrow,
  children,
  action,
  className = "",
}: {
  title?: string;
  eyebrow?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panel-heading">
          <div>
            {eyebrow && <span className="eyebrow">{eyebrow}</span>}
            <h2>{title}</h2>
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children && <div className="heading-actions">{children}</div>}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="panel-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
export function Source({ item }: { item: Entity }) {
  const url = item.source_url || item.url;
  return (
    <span className="source">
      {item.publisher && <span>{item.publisher} · </span>}
      {url ? (
        <a href={url} target="_blank" rel="noreferrer">
          查看原文 <Icon name="external" size={12} />
        </a>
      ) : (
        <span>暂无公开链接</span>
      )}
    </span>
  );
}
export function Value({ value }: { value: any }) {
  return (
    <>
      {value === null || value === undefined || value === ""
        ? "未记录"
        : typeof value === "boolean"
          ? value
            ? "是"
            : "否"
          : typeof value === "object"
            ? JSON.stringify(value)
            : String(value)}
    </>
  );
}
