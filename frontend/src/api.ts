export const API = "/api/v1";
export type Entity = Record<string, any>;
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public details?: any,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path.startsWith("/api/") ? path : API + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    let detail = data.detail || data.message || "请求未完成";
    if (Array.isArray(detail))
      detail = detail
        .map(
          (e: any) =>
            `${(e.loc || []).slice(1).join(".")}: ${e.msg || JSON.stringify(e)}`,
        )
        .join("；");
    if (typeof detail !== "string")
      detail = detail.message || JSON.stringify(detail);
    if (response.status === 401)
      window.dispatchEvent(new Event("ahr:unauthorized"));
    throw new ApiError(detail, response.status, data.detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export const post = <T = any>(path: string, data?: any) =>
  api<T>(path, {
    method: "POST",
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
export const put = <T = any>(path: string, data: any) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(data) });
export async function download(path: string, filename: string) {
  const response = await fetch(path.startsWith("/api/") ? path : API + path, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "导出失败" }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
export async function runJob(
  path: string,
  data?: any,
  update?: (job: Entity) => void,
): Promise<Entity> {
  let job = await post<Entity>(path, data);
  update?.(job);
  const end = Date.now() + 180000;
  while (
    ![
      "completed",
      "succeeded",
      "success",
      "done",
      "failed",
      "error",
      "unavailable",
    ].includes(job.status)
  ) {
    if (Date.now() > end)
      throw new Error(`任务 ${job.id} 仍在处理，可稍后刷新查看。`);
    await new Promise((resolve) => setTimeout(resolve, 850));
    job = await api<Entity>(`/jobs/${job.id}`);
    update?.(job);
  }
  if (["failed", "error"].includes(job.status))
    throw new Error(
      typeof job.error === "string"
        ? job.error
        : JSON.stringify(job.error || "任务执行失败"),
    );
  return job.result || job;
}
export function imageUrl(image: Entity) {
  return image.url?.startsWith("/api/")
    ? image.url
    : `${API}/images/${image.id}/file`;
}
export function fmtTime(value: any) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : date.toLocaleString("zh-CN", { hour12: false });
}
export function fmtNum(value: any, digits = 2) {
  return value === null || value === undefined
    ? "未测定"
    : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}
export const statusNames: Record<string, string> = {
  draft: "草案",
  review: "待专家审核",
  approved: "已审核",
  rejected: "退回修改",
  submitted: "已提交",
  pending: "待处理",
  completed: "已完成",
  running: "处理中",
  queued: "排队中",
  pass: "通过",
  warn: "待关注",
  block: "阻断",
  available: "已就绪",
  unavailable: "未配置",
  ready: "已就绪",
  template_fallback: "结构模板回退",
  stale: "待重新审核",
  superseded: "已被新版替代",
  implemented: "已实现",
  not_evaluated: "未评测",
  pending_verification: "待核验",
  requires_user_cloud_environment: "待配置云环境",
  configured: "已配置",
  manual_required: "需人工标注",
  model_unavailable: "分割模型未配置",
  model_load_failed: "分割模型加载失败",
  awaiting_expert_confirmation: "候选待人工确认",
  manual_fallback: "原文人工整理",
  human_edit: "人工修订",
};
export const roleNames: Record<string, string> = {
  surveyor: "基层文保员",
  restorer: "修复师",
  expert: "区域专家",
  manager: "管理者",
  admin: "管理员",
};
