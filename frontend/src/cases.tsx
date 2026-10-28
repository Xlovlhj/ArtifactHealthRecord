import { useEffect, useState, type ReactNode } from "react";
import { api, post, put, type Entity } from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  Icon,
  LoadState,
  Modal,
  PageHeading,
  Panel,
  Source,
  useAction,
  useApp,
  useLoad,
  Value,
} from "./ui";

export const completenessLabels: Record<string, string> = {
  abstract: "公开 / 简要摘要",
  partial: "部分结构化病例",
  complete: "字段完整病例",
};
export function CaseCard({
  item,
  children,
  onDetail,
}: {
  item: Entity;
  children?: ReactNode;
  onDetail?: () => void;
}) {
  return (
    <article className="knowledge-card case-card">
      <div className="knowledge-meta">
        <Badge value={item.completeness === "complete" ? "ready" : "neutral"}>
          {completenessLabels[item.completeness] || "公开资料摘要"}
        </Badge>
        <span className="muted">
          {item.editable ? "机构内部录入" : "公开资料 · 只读"}
        </span>
      </div>
      <h3>{item.title}</h3>
      <p>{item.text || "原始资料未提供诊断依据。"}</p>
      <div className="tags">
        {item.region && <span>{item.region}</span>}
        {item.material && <span>{item.material}</span>}
        {(item.diseases || []).map((d: string) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="case-facts">
        <div>
          <b>历史工艺 / 方案</b>
          <p>{item.plan_summary || "公开资料未报告"}</p>
        </div>
        <div>
          <b>结果与失败线索</b>
          <p>{item.outcome || "公开资料未报告，不能推定有效"}</p>
        </div>
      </div>
      {item.match_reasons?.length > 0 && (
        <p className="match-reasons">
          匹配依据：{item.match_reasons.join("；")}
        </p>
      )}
      {item.score !== null && item.score !== undefined && (
        <p className="muted">排序分：{item.score}（不是疗效或临床相似概率）</p>
      )}
      {item.missing_fields?.length > 0 && (
        <div className="callout compact amber">
          缺项：{item.missing_fields.join("、")}
        </div>
      )}
      <Source item={item} />
      <p className="license-note">
        许可 / 使用边界：
        <Value
          value={
            item.license_note ||
            item.license ||
            "须进一步核对原始资料许可；公开可访问不等于授权复用"
          }
        />
      </p>
      <div className="case-actions">
        {onDetail && <Button onClick={onDetail}>查看病例详情</Button>}
        {children}
      </div>
    </article>
  );
}

function CaseDetail({ item }: { item: Entity }) {
  return (
    <>
      <div className="inline-actions">
        <Badge value={item.completeness === "complete" ? "ready" : "neutral"}>
          {completenessLabels[item.completeness] || "资料摘要"}
        </Badge>
        <span className="muted">
          {item.id} · v{item.version || 1}
        </span>
      </div>
      <p className="muted">
        “字段完整”仅指录入项目齐备，不代表真实性或技术结论已通过专家验收。
      </p>
      <div className="form-grid">
        {[
          ["region", "地区"],
          ["material", "材质"],
          ["diseases", "病害"],
          ["publisher", "原始发布机构"],
        ].map(([key, label]) => (
          <div className="read-field" key={key}>
            <span>{label}</span>
            <b>
              <Value
                value={
                  Array.isArray(item[key]) ? item[key].join("、") : item[key]
                }
              />
            </b>
          </div>
        ))}
      </div>
      {[
        ["text", "病害与诊断依据"],
        ["plan_summary", "保护工艺与历史方案"],
        ["outcome", "效果、失败及持续观察"],
        ["expert_note", "专家意见 / 评议记录"],
        ["license_note", "来源许可与使用边界"],
      ].map(([key, label]) => (
        <section className="case-detail-section" key={key}>
          <h3>{label}</h3>
          <p>{item[key] || "原始资料未提供；不自动补全。"}</p>
        </section>
      ))}
      {item.images?.length > 0 && (
        <section className="case-detail-section">
          <h3>已获授权的病例影像</h3>
          <div className="case-image-grid">
            {item.images.map((image: Entity) => (
              <figure key={image.id}>
                <img src={image.url} alt={image.filename || "病例影像"} />
                <figcaption>{image.filename}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
      <Source item={item} />
      {item.record_id && (
        <p>
          <a href={`#records/${item.record_id}`}>关联病历：{item.record_id}</a>
        </p>
      )}
    </>
  );
}
function CaseModal({ id, onClose }: { id: string; onClose: () => void }) {
  const result = useLoad<Entity>(`/cases/${encodeURIComponent(id)}`);
  const { act, busy } = useAction();
  const { user } = useApp();
  return (
    <Modal title="病例详情与出处" onClose={onClose}>
      <LoadState
        loading={result.loading}
        error={result.error}
        retry={result.reload}
      >
        {result.data && (
          <>
            <CaseDetail item={result.data} />
            {result.data.editable &&
              ["restorer", "expert", "admin"].includes(user.role) && (
                <section className="case-detail-section">
                  <h3>追加病例影像</h3>
                  <p className="muted">
                    先在病例中填写影像许可和使用范围，再上传相应原始影像。用于检索时由服务端报告图像特征是否实际启用。
                  </p>
                  <label
                    className={`button secondary upload-button ${busy || !result.data.license_note?.trim() ? "disabled" : ""}`}
                  >
                    上传获授权的病例影像
                    <input
                      aria-label="病例影像文件"
                      type="file"
                      accept="image/png,image/jpeg,image/tiff,image/webp"
                      disabled={busy || !result.data.license_note?.trim()}
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        const body = new FormData();
                        body.append("file", file);
                        await act(async () => {
                          await api(`/cases/${id}/images`, {
                            method: "POST",
                            body,
                          });
                          result.reload();
                        }, "病例影像已保存，版本已更新");
                      }}
                    />
                  </label>
                </section>
              )}
          </>
        )}
      </LoadState>
    </Modal>
  );
}

function CaseForm({
  initial,
  onSubmit,
  busy,
}: {
  initial?: Entity;
  onSubmit: (data: Entity) => void;
  busy: boolean;
}) {
  const { dict } = useApp();
  const [value, setValue] = useState<Entity>(
    initial || {
      title: "",
      region: "甘肃",
      material: "",
      diseases: [],
      text: "",
      plan_summary: "",
      outcome: "",
      expert_note: "",
      source_url: "",
      publisher: "",
      license_note: "",
      completeness: "partial",
    },
  );
  function set(key: string, text: any) {
    setValue({ ...value, [key]: text });
  }
  const fields = [
    ["title", "病例名称"],
    ["region", "地区"],
    ["material", "材质 / 地仗与颜料"],
    ["publisher", "原始发布机构"],
    ["source_url", "原始资料链接"],
    ["record_id", "关联病历编号（可选）"],
  ];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(
          Object.fromEntries(
            [
              "title",
              "region",
              "material",
              "diseases",
              "text",
              "plan_summary",
              "outcome",
              "expert_note",
              "source_url",
              "publisher",
              "license_note",
              "record_id",
              "completeness",
            ].map((key) => [
              key,
              key === "record_id" ? value[key] || null : (value[key] ?? ""),
            ]),
          ),
        );
      }}
    >
      <div className="form-grid">
        {fields.map(([key, label]) => (
          <Field
            key={key}
            label={label}
            wide={key === "title" || key === "source_url"}
          >
            <input
              required={key === "title"}
              type={key === "source_url" ? "url" : "text"}
              value={value[key] || ""}
              onChange={(e) => set(key, e.target.value)}
            />
          </Field>
        ))}
        <Field label="病例病害" wide>
          <div className="checkbox-grid">
            {(dict.diseases || []).map((d: Entity) => (
              <label className="check-field" key={d.type}>
                <input
                  type="checkbox"
                  checked={(value.diseases || []).includes(d.type)}
                  onChange={(e) =>
                    set(
                      "diseases",
                      e.target.checked
                        ? [...(value.diseases || []), d.type]
                        : (value.diseases || []).filter(
                            (v: string) => v !== d.type,
                          ),
                    )
                  }
                />
                {d.type}
              </label>
            ))}
          </div>
        </Field>
        {[
          ["text", "病害与诊断依据"],
          ["plan_summary", "保护工艺与历史方案"],
          ["outcome", "效果、失败及持续观察"],
          ["expert_note", "专家意见 / 评议记录"],
          ["license_note", "来源许可与使用边界"],
        ].map(([key, label]) => (
          <Field key={key} label={label} wide>
            <textarea
              required={key === "text"}
              rows={3}
              value={value[key] || ""}
              onChange={(e) => set(key, e.target.value)}
              placeholder="仅填写实际资料中能够核对的信息，未知内容留空。"
            />
          </Field>
        ))}
        <Field
          label="病例完整程度"
          wide
          hint="字段完整需包含诊断依据、工艺、结果、来源链接及许可；不代表通过专业验收。"
        >
          <select
            value={value.completeness || "partial"}
            onChange={(e) => set("completeness", e.target.value)}
          >
            {Object.entries(completenessLabels).map(([key, title]) => (
              <option key={key} value={key}>
                {title}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="form-actions">
        <Button busy={busy} variant="primary" type="submit">
          {initial ? "保存病例修订" : "创建病例"}
        </Button>
      </div>
    </form>
  );
}

export function CaseLibrary() {
  const { user, dict } = useApp();
  const { act, busy } = useAction();
  const [filter, setFilter] = useState<Entity>({
      q: "",
      disease: "",
      region: "",
      material: "",
    }),
    [query, setQuery] = useState(""),
    [editing, setEditing] = useState<Entity | null | undefined>(undefined),
    [detail, setDetail] = useState<string | null>(null);
  const list = useLoad<Entity>(`/cases?${query}`);
  const editable = ["restorer", "expert", "admin"].includes(user.role);
  return (
    <>
      <PageHeading
        eyebrow="STRUCTURED CASE LIBRARY"
        title="保护病例库"
        description="把诊断依据、历史工艺、结果与专家意见组织成可检索的病例；公开摘要和机构完整病例分别标记。"
      >
        {editable && (
          <Button
            variant="primary"
            icon="plus"
            onClick={() => setEditing(null)}
          >
            录入保护病例
          </Button>
        )}
      </PageHeading>
      <CaseFilters
        filter={filter}
        setFilter={setFilter}
        diseases={dict.diseases || []}
        onSearch={() => setQuery(new URLSearchParams(filter).toString())}
      />
      <div className="callout compact">
        来源可查与病例完整是两个不同维度。未报告的材料、工艺或疗效保留为空，不用新闻摘要冒充完整修复档案。
      </div>
      <LoadState loading={list.loading} error={list.error} retry={list.reload}>
        {list.data?.items?.length ? (
          <>
            <p className="results-label">
              {list.data.count ?? list.data.items.length} 条病例资料
            </p>
            <div className="knowledge-grid">
              {list.data.items.map((item: Entity) => (
                <CaseCard
                  key={item.id}
                  item={item}
                  onDetail={() => setDetail(item.id)}
                >
                  {editable && item.editable && (
                    <Button
                      icon="record"
                      onClick={async () => {
                        const data = await act(() => api(`/cases/${item.id}`));
                        if (data) setEditing(data);
                      }}
                    >
                      编辑病例
                    </Button>
                  )}
                </CaseCard>
              ))}
            </div>
          </>
        ) : (
          <Panel>
            <Empty
              title="暂无匹配病例"
              description="可调整过滤条件，或录入已获授权的保护病例。"
              icon="book"
            />
          </Panel>
        )}
      </LoadState>
      {editing !== undefined && (
        <Modal
          title={editing ? "修订保护病例" : "录入保护病例"}
          onClose={() => setEditing(undefined)}
        >
          <CaseForm
            initial={editing || undefined}
            busy={busy}
            onSubmit={async (data) => {
              const saved = await act(
                () =>
                  editing
                    ? put(`/cases/${editing.id}`, {
                        ...data,
                        expected_version: editing.version,
                      })
                    : post("/cases", data),
                "病例已保存并记录来源",
              );
              if (saved) {
                setEditing(undefined);
                list.reload();
              }
            }}
          />
        </Modal>
      )}
      {detail && <CaseModal id={detail} onClose={() => setDetail(null)} />}
    </>
  );
}
function CaseFilters({
  filter,
  setFilter,
  diseases,
  onSearch,
  children,
}: {
  filter: Entity;
  setFilter: (f: Entity) => void;
  diseases: Entity[];
  onSearch: () => void;
  children?: ReactNode;
}) {
  return (
    <form
      className="filters wrap"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch();
      }}
    >
      <div className="search-field">
        <Icon name="search" />
        <input
          value={filter.q || ""}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          placeholder="病例名称、工艺或诊断关键词"
          aria-label="病例检索词"
        />
      </div>
      <select
        value={filter.disease || ""}
        onChange={(e) => setFilter({ ...filter, disease: e.target.value })}
        aria-label="病例病害筛选"
      >
        <option value="">全部病害</option>
        {diseases.map((d) => (
          <option key={d.type}>{d.type}</option>
        ))}
      </select>
      <input
        className="short-input"
        value={filter.region || ""}
        onChange={(e) => setFilter({ ...filter, region: e.target.value })}
        placeholder="地区，如甘肃"
        aria-label="病例地区筛选"
      />
      <input
        className="short-input"
        value={filter.material || ""}
        onChange={(e) => setFilter({ ...filter, material: e.target.value })}
        placeholder="材质 / 地仗"
        aria-label="病例材质筛选"
      />
      {children}
      <Button type="submit" variant="primary">
        检索病例
      </Button>
    </form>
  );
}

export function CaseEvidenceWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { dict, user } = useApp(),
    { act, busy } = useAction();
  const [filter, setFilter] = useState<Entity>({
      q: "",
      disease: "",
      region: "",
      material: "",
    }),
    [query, setQuery] = useState(""),
    [includeImage, setIncludeImage] = useState(false),
    [imageId, setImageId] = useState(String(record.images?.[0]?.id || "")),
    [selected, setSelected] = useState<string[]>(record.evidence_ids || []),
    [detail, setDetail] = useState<string | null>(null);
  const similar = useLoad<Entity>(
    `/records/${record.id}/similar-cases?${query}`,
  );
  const editable = ["surveyor", "restorer", "expert", "admin"].includes(
    user.role,
  );
  useEffect(() => setSelected(record.evidence_ids || []), [record.version]);
  const isDirty =
    JSON.stringify([...selected].sort()) !==
    JSON.stringify([...(record.evidence_ids || [])].sort());
  function toggle(id: string) {
    setSelected((values) =>
      values.includes(id) ? values.filter((v) => v !== id) : [...values, id],
    );
  }
  return (
    <>
      <Panel title="检索与选择相似病例" eyebrow="CASE MATCHING WITH EVIDENCE">
        <CaseFilters
          filter={filter}
          setFilter={setFilter}
          diseases={dict.diseases || []}
          onSearch={() =>
            setQuery(
              new URLSearchParams({
                ...filter,
                ...(includeImage && imageId ? { image_id: imageId } : {}),
              }).toString(),
            )
          }
        />
        <div className="inline-actions">
          <label className="check-field">
            <input
              type="checkbox"
              checked={includeImage}
              disabled={!record.images?.length}
              onChange={(e) => setIncludeImage(e.target.checked)}
            />
            同时使用所选影像检索
          </label>
          {includeImage && (
            <select
              aria-label="病例检索影像"
              value={imageId}
              onChange={(e) => setImageId(e.target.value)}
            >
              {(record.images || []).map((img: Entity) => (
                <option value={img.id} key={img.id}>
                  {img.filename}
                </option>
              ))}
            </select>
          )}
          {editable && (
            <Button
              variant="primary"
              busy={busy}
              disabled={!isDirty}
              onClick={() =>
                act(async () => {
                  await put(`/records/${record.id}/evidence`, {
                    expected_version: record.version,
                    ids: selected,
                  });
                  reload();
                }, "所选病例已关联病历，方案需依据当前版本生成")
              }
            >
              保存所选病例（{selected.length}）
            </Button>
          )}
          {isDirty && <Badge value="warn">选择尚未保存</Badge>}
        </div>
        <p className="muted">
          是否实际采用图像特征，由检索结果返回的方法与降级说明确定；不把纯文本检索标为多模态。
        </p>
        <LoadState
          loading={similar.loading}
          error={similar.error}
          retry={similar.reload}
        >
          {similar.data && (
            <div className="callout compact">
              <div>
                <b>本次检索方法</b>
                <p>
                  <Value value={similar.data.method} />
                </p>
                {similar.data.image_retrieval&&<div className="retrieval-status"><Badge value={similar.data.image_retrieval.status==="ok"?"ready":"warn"}>{similar.data.image_retrieval.status==="ok"?"已使用图像特征":"图像检索未启用 / 已回退"}</Badge><p><Value value={similar.data.image_retrieval.message||similar.data.image_retrieval.reason||similar.data.image_retrieval.limitations}/></p>{similar.data.image_retrieval.model_version&&<small>模型：{similar.data.image_retrieval.model_version}</small>}<details><summary>查看检索方法与模型状态</summary><pre>{JSON.stringify({...similar.data.image_retrieval,items:undefined},null,2)}</pre></details></div>}
                {similar.data.limitations && (
                  <p>
                    <Value value={similar.data.limitations} />
                  </p>
                )}
              </div>
            </div>
          )}
          {similar.data?.items?.length ? (
            <div className="knowledge-grid">
              {similar.data.items.map((item: Entity) => (
                <CaseCard
                  key={item.id}
                  item={item}
                  onDetail={() => setDetail(item.id)}
                >
                  {editable && (
                    <Button
                      variant={selected.includes(item.id) ? "secondary" : ""}
                      onClick={() => toggle(item.id)}
                      icon={selected.includes(item.id) ? "check" : "plus"}
                    >
                      {selected.includes(item.id)
                        ? "移出所选病例"
                        : "选为方案依据"}
                    </Button>
                  )}
                </CaseCard>
              ))}
            </div>
          ) : (
            <Empty
              title="没有匹配病例"
              description="调整病害、材质或地区条件，也可在病例库录入已获授权的资料。"
              icon="book"
            />
          )}
        </LoadState>
      </Panel>
      <Panel
        title="已关联的病例与专家意见"
        action={
          <a className="text-link" href="#cases">
            管理保护病例库 <Icon name="arrow" size={15} />
          </a>
        }
      >
        {record.evidence_sources?.length ? (
          <div className="knowledge-grid">
            {record.evidence_sources.map((item: Entity) => (
              <article className="knowledge-card" key={item.id}>
                <Badge value="neutral">
                  {item.kind === "expert" || item.kind === "expert_note"
                    ? "专家意见"
                    : "病例依据"}
                </Badge>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
                <small className="muted">依据 ID：{item.id}</small>
                {item.source_url && <Source item={item} />}
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="尚未关联病例或专家意见"
            description="在上方筛选并保存病例；会诊意见由系统关联，生成时保留版本快照。"
          />
        )}
      </Panel>
      <Panel title="规范与材料研究资料">
        <p className="muted">
          标准条款及研究文献在循证资料页检索，生成的方案引用将保存当次证据快照。
        </p>
        <a href="#knowledge" className="button secondary">
          进入循证资料
        </a>
      </Panel>
      {detail && <CaseModal id={detail} onClose={() => setDetail(null)} />}
    </>
  );
}
