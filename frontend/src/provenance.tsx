import { useEffect, useState } from "react";
import { fmtTime, imageUrl, post, put, type Entity } from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  LoadState,
  Modal,
  PageHeading,
  Panel,
  useAction,
  useApp,
  useLoad,
} from "./ui";
import { ReferenceImages } from "./reference-images";

export const sourceNames: Record<string, string> = {
  unknown: "来源未核实",
  field_capture: "现场采集",
  public_dataset: "公开数据集 / 馆藏公开影像",
  partner_archive: "合作单位档案",
  synthetic: "合成 / 教学影像",
};
const useNames: Record<string, string> = {
  internal_display: "内部展示",
  research: "研究分析",
  training: "模型训练",
  evaluation: "真实数据评测",
  redistribution: "公开再分发",
};
export const emptyProvenance = (): Entity => ({
  source_type: "unknown",
  allowed_uses: [],
});
const editableProvenance = (p: Entity): Entity =>
  Object.fromEntries(
    [
      "source_type",
      "source_title",
      "source_url",
      "creator",
      "license_name",
      "license_url",
      "rights_holder",
      "permission_evidence",
      "allowed_uses",
      "captured_at",
      "site_group",
      "notes",
    ].map((key) => [
      key,
      p[key] ??
        (key === "allowed_uses" ? [] : key === "source_type" ? "unknown" : ""),
    ]),
  );
export function sourceStatus(image: Entity, demo = false) {
  const p = image.provenance || {};
  if (p.source_type === "synthetic" || (!p.source_type && demo))
    return { label: "合成 / 教学素材", tone: "warn" };
  if (!p.source_type || p.source_type === "unknown")
    return { label: "来源未核实", tone: "warn" };
  const status = p.review_status || p.review?.status;
  if (status === "verified")
    return { label: "来源与许可已复核", tone: "ready" };
  if (status === "rejected") return { label: "来源复核退回", tone: "rejected" };
  return { label: "来源已声明 · 待复核", tone: "pending" };
}
export function SourceBadge({
  image,
  demo = false,
}: {
  image: Entity;
  demo?: boolean;
}) {
  const status = sourceStatus(image, demo);
  return <Badge value={status.tone}>{status.label}</Badge>;
}
function SafeLink({ value, label }: { value?: string; label: string }) {
  return value && /^https?:\/\//i.test(value) ? (
    <a href={value} target="_blank" rel="noreferrer">
      {label} ↗
    </a>
  ) : (
    <span className="muted">{value || "未记录"}</span>
  );
}
export function ProvenanceFields({
  value,
  onChange,
}: {
  value: Entity;
  onChange: (value: Entity) => void;
}) {
  const update = (key: string, content: any) =>
    onChange({ ...value, [key]: content });
  return (
    <>
      <div className="form-grid">
        <Field label="影像来源类型">
          <select
            value={value.source_type || "unknown"}
            onChange={(e) => {
              onChange({
                ...value,
                source_type: e.target.value,
                allowed_uses:
                  e.target.value === "synthetic"
                    ? (value.allowed_uses || []).filter(
                        (x: string) => x !== "evaluation",
                      )
                    : value.allowed_uses || [],
              });
            }}
          >
            {Object.entries(sourceNames).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="数据集 / 来源名称">
          <input
            value={value.source_title || ""}
            onChange={(e) => update("source_title", e.target.value)}
            placeholder="具体数据集、采集批次或馆藏档案名称"
          />
        </Field>
        <Field label="原始来源链接">
          <input
            type="url"
            value={value.source_url || ""}
            onChange={(e) => update("source_url", e.target.value)}
            placeholder="https://…（数据条目或官方原文）"
          />
        </Field>
        <Field label="拍摄者 / 作者">
          <input
            value={value.creator || ""}
            onChange={(e) => update("creator", e.target.value)}
          />
        </Field>
        <Field label="许可证名称">
          <input
            value={value.license_name || ""}
            onChange={(e) => update("license_name", e.target.value)}
            placeholder="如 CC0 1.0、CC BY 4.0、合作授权"
          />
        </Field>
        <Field label="许可证原文链接">
          <input
            type="url"
            value={value.license_url || ""}
            onChange={(e) => update("license_url", e.target.value)}
            placeholder="https://…"
          />
        </Field>
        <Field label="权利人 / 授权单位">
          <input
            value={value.rights_holder || ""}
            onChange={(e) => update("rights_holder", e.target.value)}
          />
        </Field>
        <Field label="采集日期">
          <input
            type="date"
            value={(value.captured_at || "").slice(0, 10)}
            onChange={(e) => update("captured_at", e.target.value)}
          />
        </Field>
        <Field
          label="壁画 / 遗址分组编号"
          hint="同一壁画的局部、切片和复拍使用同一编号，用于防止训练与测试数据泄漏。"
        >
          <input
            value={value.site_group || ""}
            onChange={(e) => update("site_group", e.target.value)}
            placeholder="使用脱敏编号，例如 site-a-wall-01"
          />
        </Field>
        <Field label="授权证据与使用限制">
          <textarea
            rows={3}
            value={value.permission_evidence || ""}
            onChange={(e) => update("permission_evidence", e.target.value)}
            placeholder="授权书编号、官方许可页面、适用范围和限制。来源公开不等于允许训练或再分发。"
          />
        </Field>
      </div>
      <fieldset className="provenance-uses">
        <legend>授权允许的用途（按证据勾选）</legend>
        <div className="checkbox-grid">
          {Object.entries(useNames).map(([key, label]) => (
            <label className="check-field" key={key}>
              <input
                type="checkbox"
                checked={(value.allowed_uses || []).includes(key)}
                disabled={
                  key === "evaluation" && value.source_type === "synthetic"
                }
                onChange={(e) =>
                  update(
                    "allowed_uses",
                    e.target.checked
                      ? [...(value.allowed_uses || []), key]
                      : (value.allowed_uses || []).filter(
                          (x: string) => x !== key,
                        ),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <Field label="来源与采集备注">
        <textarea
          rows={2}
          value={value.notes || ""}
          onChange={(e) => update("notes", e.target.value)}
          placeholder="记录拍摄条件、脱敏或裁剪过程、数据局限；不填写推测的文物信息。"
        />
      </Field>
      <p className="muted">
        未获得的许可保持未勾选。来源填写后仍需复核；合成图只用于工程演示或训练增强，不计入真实评测样本。
      </p>
    </>
  );
}

export function ImageProvenance({
  image,
  record,
  reload,
  hasUnsavedAnnotations = false,
}: {
  image: Entity;
  record: Entity;
  reload: () => void;
  hasUnsavedAnnotations?: boolean;
}) {
  const { user } = useApp(),
    { act, busy } = useAction();
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState<Entity>(emptyProvenance()),
    [comment, setComment] = useState("");
  const p = image.provenance || {},
    review = p.review || {};
  useEffect(() => {
    setEditing(false);
    setComment("");
  }, [image.id]);
  const editable = ["surveyor", "restorer", "admin"].includes(user.role);
  return (
    <Panel
      title="影像来源与使用授权"
      eyebrow="IMAGE PROVENANCE"
      action={<SourceBadge image={image} demo={record.is_demo} />}
    >
      <div className="provenance-summary">
        <div>
          <span>来源</span>
          <b>{sourceNames[p.source_type] || "来源未核实"}</b>
          <p>{p.source_title || "尚未记录来源名称"}</p>
        </div>
        <div>
          <span>许可</span>
          <b>{p.license_name || "许可未记录"}</b>
          <p>
            {(p.allowed_uses || [])
              .map((x: string) => useNames[x] || x)
              .join(" / ") || "尚未确认使用范围"}
          </p>
        </div>
        <div>
          <span>壁画 / 遗址分组</span>
          <b>{p.site_group || "未设置"}</b>
          <p>{p.creator ? `作者：${p.creator}` : "作者未记录"}</p>
        </div>
        <div>
          <span>原文与授权</span>
          <SafeLink value={p.source_url} label="查看影像来源" />
          <br />
          <SafeLink value={p.license_url} label="查看许可证原文" />
        </div>
      </div>
      {p.permission_evidence && (
        <p>
          <b>授权证据：</b>
          {p.permission_evidence}
        </p>
      )}
      {image.provenance_issues?.length > 0 && (
        <div className="callout amber compact">
          <div>
            <b>来源资料待补齐</b>
            <ul>
              {image.provenance_issues.map((issue: string) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {p.notes && <p className="muted">{p.notes}</p>}
      {(review.comment || p.review_comment) && (
        <div className="callout compact">
          来源复核：{review.comment || p.review_comment}（
          {fmtTime(review.reviewed_at || p.reviewed_at)}）
        </div>
      )}
      <details className="provenance-details">
        <summary>采集记录与文件校验信息</summary>
        <dl>
          {p.view_type_label && (
            <>
              <dt>影像视图</dt>
              <dd>{p.view_type_label}</dd>
            </>
          )}
          <dt>采集日期</dt>
          <dd>{p.captured_at || "未记录"}</dd>
          <dt>权利人</dt>
          <dd>{p.rights_holder || "未记录"}</dd>
          <dt>上传时间</dt>
          <dd>{fmtTime(image.created_at)}</dd>
          <dt>SHA-256</dt>
          <dd className="file-checksum">{image.sha256 || "未记录"}</dd>
        </dl>
      </details>
      {hasUnsavedAnnotations && (
        <p className="callout amber compact">
          当前影像有未保存的病害标注，请先保存标注，再修改或复核来源，避免版本更新覆盖草稿。
        </p>
      )}
      {editable && (
        <Button
          disabled={hasUnsavedAnnotations}
          onClick={() => {
            setDraft(editableProvenance(p));
            setEditing(true);
          }}
        >
          补录 / 修改影像来源
        </Button>
      )}
      {["expert", "admin"].includes(user.role) && (
        <details className="provenance-details">
          <summary>复核来源与授权证据</summary>
          <p className="muted">
            由来源录入人以外的专家或管理员核对。复核只确认来源与许可资料，不替代图像真伪鉴定或病害诊断。
            {p.recorded_by === user.id
              ? "本次来源由你录入，请由另一账号复核。"
              : ""}
          </p>
          <Field label="影像来源复核意见">
            <textarea
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="说明核查的原始页面、授权范围及是否需要补充证据。"
            />
          </Field>
          <div className="inline-actions">
            {[
              ["verified", "确认来源与许可"],
              ["rejected", "退回补充来源"],
            ].map(([decision, label]) => (
              <Button
                key={decision}
                busy={busy}
                disabled={
                  !comment.trim() ||
                  p.recorded_by === user.id ||
                  hasUnsavedAnnotations
                }
                onClick={() =>
                  act(async () => {
                    await post(`/images/${image.id}/provenance/review`, {
                      expected_version: record.version,
                      decision,
                      comment,
                    });
                    setComment("");
                    reload();
                  }, "来源复核已留痕")
                }
              >
                {label}
              </Button>
            ))}
          </div>
        </details>
      )}
      {editing && (
        <Modal title="编辑影像来源与授权" onClose={() => setEditing(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(async () => {
                await put(`/images/${image.id}/provenance`, {
                  expected_version: record.version,
                  provenance: draft,
                });
                setEditing(false);
                reload();
              }, "来源已保存，需按新版本复核");
            }}
          >
            <ProvenanceFields value={draft} onChange={setDraft} />
            <Button
              type="submit"
              variant="primary"
              busy={busy}
              disabled={hasUnsavedAnnotations}
            >
              保存影像来源
            </Button>
          </form>
        </Modal>
      )}
    </Panel>
  );
}

export function DataReadinessPage() {
  const { data, loading, error, reload } = useLoad<Entity>("/data/readiness");
  const [filter, setFilter] = useState("all");
  const images: Entity[] = data?.images || [];
  const visible = images.filter(
    (image) =>
      filter === "all" ||
      (image.provenance?.source_type || "unknown") === filter,
  );
  const counts = data?.counts || {};
  return (
    <>
      <PageHeading
        eyebrow="DATA & EVIDENCE READINESS"
        title="数据来源与缺口"
        description="逐张查看影像出处、许可和复核状态，区分真实数据、教学素材与待核实资料。"
      >
        <Button onClick={reload}>刷新台账</Button>
      </PageHeading>
      <ReferenceImages />
      <LoadState loading={loading} error={error} retry={reload}>
        {data && (
          <>
            <div className="data-count-grid">
              {[
                ["影像总数", counts.total_images],
                ["合成 / 教学影像", counts.synthetic_images],
                ["来源未核实", counts.unknown_images],
                ["已复核真实影像", counts.verified_real_images],
                ["真实评测候选", counts.evaluation_ready_images],
              ].map(([title, count]) => (
                <div className="data-count-card" key={title}>
                  <span>{title}</span>
                  <strong>{count ?? "未提供"}</strong>
                </div>
              ))}
            </div>
            <div className="callout amber">
              <div>
                <b>工程跑通与真实数据验证分开记录</b>
                <p>
                  项目书要求初赛收集 30–50 张有出处、有许可的壁画局部图、至少
                  100
                  个病害实例、专家审核，以及真实修复方案参照。来源复核只确认资料依据；模型指标仍需专家标注、独立测试集和可复现实验。
                </p>
              </div>
            </div>
            {Array.isArray(data.gaps) && data.gaps.length > 0 && (
              <Panel title="需要补齐的证据">
                <div className="data-gap-list">
                  {data.gaps.map((gap: any, i: number) => (
                    <div key={gap.id || i}>
                      <b>
                        {typeof gap === "string"
                          ? gap
                          : gap.title || gap.name || gap.id}
                      </b>
                      {typeof gap !== "string" && (
                        <>
                          <p>{gap.description || gap.detail || gap.reason}</p>
                          {gap.current != null && (
                            <small>
                              当前 {gap.current}
                              {gap.target != null
                                ? ` / 目标 ${gap.target}`
                                : ""}
                            </small>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </Panel>
            )}
            <Panel
              title="影像来源台账"
              className="provenance-ledger"
              action={
                <select
                  aria-label="按影像来源筛选"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">全部来源</option>
                  {Object.entries(sourceNames).map(([key, title]) => (
                    <option key={key} value={key}>
                      {title}
                    </option>
                  ))}
                </select>
              }
            >
              {visible.length ? (
                <div className="provenance-image-grid">
                  {visible.map((image) => (
                    <article className="provenance-image-card" key={image.id}>
                      <a
                        href={`#records/${image.record_id}?tab=images&image=${encodeURIComponent(image.id)}`}
                      >
                        <img
                          src={imageUrl(image)}
                          alt={image.filename || "待核实影像"}
                          loading="lazy"
                        />
                      </a>
                      <div>
                        <SourceBadge image={image} demo={image.is_demo} />
                        <h3>
                          {image.provenance?.source_title || image.filename}
                        </h3>
                        <p>
                          {image.record_name ||
                            image.artifact_name ||
                            image.record_id}
                        </p>
                        <p>
                          许可：{image.provenance?.license_name || "未记录"}
                        </p>
                        <p>分组：{image.provenance?.site_group || "未设置"}</p>
                        <SafeLink
                          value={image.provenance?.source_url}
                          label="核对原始来源"
                        />
                        <br />
                        <a
                          className="text-link"
                          href={`#records/${image.record_id}?tab=images&image=${encodeURIComponent(image.id)}`}
                        >
                          进入影像与来源记录 →
                        </a>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <Empty
                  title="此来源类型下暂无影像"
                  description="上传后补全来源和许可；不使用示例数量代替真实采集数量。"
                />
              )}
            </Panel>
          </>
        )}
      </LoadState>
    </>
  );
}
