import { useState, type FormEvent } from "react";
import { riskLabels } from "./clinical";
import { type Entity, fmtTime, post, statusNames } from "./api";
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

export function Dashboard() {
  const { data, loading, error, reload } = useLoad<Entity>("/dashboard");
  const { user } = useApp();
  const stats = data
    ? [
        ["文物病历", data.records, "record", "份保护记录"],
        ["调查影像", data.images, "image", "张原始与复查影像"],
        ["病害标注", data.diseases, "polygon", "处人工保存标注"],
        ["待审方案", data.pending_reviews, "people", "份等待专家会诊"],
      ]
    : [];
  return (
    <>
      <PageHeading
        eyebrow="CONSERVATION WORKSPACE"
        title="让保护，有据可循。"
        description="从现场的每一处痕迹，到一份可追溯的文物病历。"
      >
        <a href="#records" className="button primary">
          <Icon name="plus" size={18} />
          新建调查病历
        </a>
      </PageHeading>
      <LoadState loading={loading} error={error} retry={reload}>
        {data && (
          <>
            <div className="hero-banner">
              <div>
                <span className="eyebrow">今日工作空间</span>
                <h2>{user.name || "保护工作者"}，欢迎回来。</h2>
                <p>查看近期调查、完善病害依据，接续每一次保护记录。</p>
                <a href="#consultations">
                  进入专家会诊 <Icon name="arrow" size={17} />
                </a>
              </div>
              <div className="hero-stamp" aria-hidden="true">
                <span>
                  守护
                  <br />
                  有迹
                </span>
                <small>RECORD · EVIDENCE · CARE</small>
              </div>
            </div>
            <div className="stats-grid">
              {stats.map(([name, count, icon, desc]) => (
                <div className="stat-card" key={name}>
                  <div className="stat-head">
                    <span>{name}</span>
                    <Icon name={icon as string} />
                  </div>
                  <strong>
                    {count ?? 0}
                    <small>
                      {name === "调查影像"
                        ? "张"
                        : name === "病害标注"
                          ? "处"
                          : "份"}
                    </small>
                  </strong>
                  <span className="muted">{desc}</span>
                </div>
              ))}
            </div>
            <div className="dashboard-grid">
              <Panel
                title="最近的保护记录"
                eyebrow="RECENT RECORDS"
                action={
                  <a href="#records" className="text-link">
                    全部病历 <Icon name="arrow" size={15} />
                  </a>
                }
              >
                {data.recent?.length ? (
                  <div className="recent-list">
                    {data.recent.slice(0, 5).map((item: Entity) => (
                      <a
                        href={`#records/${item.id}`}
                        className="recent-row"
                        key={item.id}
                      >
                        <div className="record-glyph">
                          <Icon name="record" />
                        </div>
                        <div className="recent-copy">
                          <b>{item.name || item.artifact?.name || item.id}</b>
                          <span>
                            {item.region ||
                              item.artifact?.region ||
                              "地区未记录"}{" "}
                            · {fmtTime(item.updated_at || item.created_at)}
                          </span>
                        </div>
                        <Badge value={item.status} />
                        <Icon name="arrow" size={16} />
                      </a>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="保护档案，从第一份病历开始"
                    description="建立调查记录并上传影像后，近期工作将在这里出现。"
                  />
                )}
              </Panel>
              <Panel title="病害分布" eyebrow="ANNOTATION OVERVIEW">
                {data.by_disease?.length ? (
                  <div className="bar-chart">
                    {data.by_disease.map((item: Entity) => (
                      <div key={item.name}>
                        <div className="bar-label">
                          <span>{item.name}</span>
                          <b>{item.count} 处</b>
                        </div>
                        <div className="bar-track">
                          <i
                            style={{
                              width: `${(100 * item.count) / Math.max(...data.by_disease.map((i: Entity) => i.count), 1)}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="尚无病害统计"
                    description="统计来自已保存的病害标注。"
                    icon="polygon"
                  />
                )}
                <p className="panel-footnote">
                  按标注数量汇总；不同影像的重复区域未去重。
                </p>
              </Panel>
            </div>
            <div className="two-column">
              <Panel
                title="人工风险评估分布"
                eyebrow="EVIDENCE-BASED HUMAN ASSESSMENT"
              >
                <p className="muted">
                  按病历中人工填写的风险等级汇总，未评估与低风险分别计数。
                </p>
                {data.by_risk?.length ? (
                  <div className="bar-chart">
                    {data.by_risk.map((item: Entity) => (
                      <div key={item.name}>
                        <div className="bar-label">
                          <span>{riskLabels[item.name] || item.name}</span>
                          <b>{item.count} 份</b>
                        </div>
                        <div className="bar-track">
                          <i
                            style={{
                              width: `${(100 * item.count) / Math.max(...data.by_risk.map((row: Entity) => row.count), 1)}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty title="暂无人工风险评估数据" />
                )}
              </Panel>
              <Panel title="病历工作进度" eyebrow="RECORD WORKFLOW">
                {data.by_status?.length ? (
                  <div className="bar-chart">
                    {data.by_status.map((item: Entity) => (
                      <div className="bar-label" key={item.name}>
                        <Badge value={item.name} />
                        <b>{item.count} 份</b>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    接口暂未提供分阶段统计。可在病历列表按状态查看实际进度。
                  </p>
                )}
              </Panel>
            </div>
            <div className="process-strip">
              {[
                ["01", "采集与建档", "整理现状影像与调查信息"],
                ["02", "病害与证据", "人工校正、标尺与病害图"],
                ["03", "方案与会诊", "13 章方案、规则检查与审核"],
                ["04", "归档与追溯", "保存版本、来源与审计记录"],
              ].map(([number, title, desc]) => (
                <div key={number}>
                  <span>{number}</span>
                  <b>{title}</b>
                  <p>{desc}</p>
                </div>
              ))}
            </div>
            <CapabilitySummary capabilities={data.capabilities} />
          </>
        )}
      </LoadState>
    </>
  );
}
function CapabilitySummary({ capabilities }: { capabilities?: Entity }) {
  return (
    <div className="callout">
      <Icon name="audit" />
      <div>
        <b>运行能力透明可查</b>
        <p>
          分割结果须人工确认，草案须专家审核。模型、规则和存储的真实启用状态可在
          <a href="#system">运行状态</a>查看。
          影像是否真实、来源是否有许可及还缺哪些数据，可在
          <a href="#data">数据来源与缺口</a>逐张核对。
          {capabilities?.llm?.provider === "template_fallback"
            ? " 当前方案生成使用结构模板。"
            : ""}
        </p>
      </div>
    </div>
  );
}

export function RecordForm({
  initial,
  onSubmit,
  busy = false,
  submitLabel = "创建病历",
  children,
}: {
  initial?: Entity;
  onSubmit: (data: Entity) => void;
  busy?: boolean;
  submitLabel?: string;
  children?: React.ReactNode;
}) {
  const [artifact, setArtifact] = useState<Entity>(
    initial?.artifact || {
      name: "",
      type: "石窟寺壁画",
      era: "",
      region: "甘肃",
      location: "",
      area_m2: "",
      support_type: "",
      ground_type: "",
      pigment_type: "",
      sensitivity: "internal",
    },
  );
  const [survey, setSurvey] = useState<Entity>(
    initial?.survey || {
      date: new Date().toLocaleDateString("en-CA"),
      weather: "",
      light: "",
      equipment: "",
      humidity: "",
      water_leak: null,
    },
  );
  const [chief, setChief] = useState(initial?.chief_complaint || ""),
    [history, setHistory] = useState(initial?.history || "");
  const artifactFields = [
    ["name", "文物 / 壁画名称", "例如：教学壁画调查样本"],
    ["type", "文物类型", "石窟寺壁画"],
    ["region", "地区", "甘肃"],
    ["era", "年代", "未确定时留空"],
    ["location", "保存位置", "内部位置描述"],
    ["area_m2", "调查面积（m²）", "请输入实测面积"],
    ["support_type", "支撑体", "例如：岩体、墙体"],
    ["ground_type", "地仗层", "材料或检测记录"],
    ["pigment_type", "颜料类型", "材料或检测记录"],
  ];
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          artifact: {
            ...artifact,
            area_m2:
              artifact.area_m2 == null || artifact.area_m2 === ""
                ? null
                : Number(artifact.area_m2),
          },
          survey: {
            ...survey,
            humidity:
              survey.humidity == null || survey.humidity === ""
                ? null
                : Number(survey.humidity),
          },
          chief_complaint: chief,
          history,
        });
      }}
    >
      <div className="form-section-label">01 / 文物基本信息</div>
      <div className="form-grid">
        {artifactFields.map(([key, label, placeholder]) => (
          <Field key={key} label={label} wide={key === "name"}>
            {key === "type" ? (
              <select
                value={artifact.type}
                onChange={(e) =>
                  setArtifact({ ...artifact, type: e.target.value })
                }
              >
                {["石窟寺壁画", "寺观壁画", "墓葬壁画", "馆藏壁画"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            ) : (
              <input
                required={key === "name" || key === "type"}
                type={key === "area_m2" ? "number" : "text"}
                min={key === "area_m2" ? 0.000001 : undefined}
                step={key === "area_m2" ? "any" : undefined}
                value={artifact[key] ?? ""}
                placeholder={placeholder}
                onChange={(e) =>
                  setArtifact({ ...artifact, [key]: e.target.value })
                }
              />
            )}
          </Field>
        ))}
      </div>
      <Field
        label="资料敏感级别"
        hint="敏感资料的归档、原图和方案导出须获得机构管理员针对当前病历版本的批准。"
      >
        <select
          value={artifact.sensitivity || "internal"}
          onChange={(e) =>
            setArtifact({ ...artifact, sensitivity: e.target.value })
          }
        >
          <option value="internal">内部资料</option>
          <option value="sensitive">敏感资料</option>
        </select>
      </Field>
      <div className="form-section-label">02 / 现场调查</div>
      <div className="form-grid">
        {[
          ["date", "调查日期"],
          ["weather", "天气"],
          ["light", "光照条件"],
          ["equipment", "采集设备"],
          ["humidity", "相对湿度（%）"],
        ].map(([key, label]) => (
          <Field label={label} key={key}>
            <input
              type={
                key === "date" ? "date" : key === "humidity" ? "number" : "text"
              }
              min={key === "humidity" ? 0 : undefined}
              max={key === "humidity" ? 100 : undefined}
              step={key === "humidity" ? "any" : undefined}
              value={survey[key] ?? ""}
              onChange={(e) => setSurvey({ ...survey, [key]: e.target.value })}
            />
          </Field>
        ))}
        <Field label="渗水迹象">
          <select
            value={
              survey.water_leak === null || survey.water_leak === undefined
                ? "unknown"
                : String(survey.water_leak)
            }
            onChange={(e) =>
              setSurvey({
                ...survey,
                water_leak:
                  e.target.value === "unknown"
                    ? null
                    : e.target.value === "true",
              })
            }
          >
            <option value="unknown">未调查 / 未确定</option>
            <option value="false">未见渗水</option>
            <option value="true">有渗水迹象</option>
          </select>
        </Field>
        <Field label="现状主诉" wide>
          <textarea
            rows={3}
            value={chief}
            placeholder="记录观察到的现象、位置和变化，不把推测写成事实。"
            onChange={(e) => setChief(e.target.value)}
          />
        </Field>
        <Field label="保护与修复历史" wide>
          <textarea
            rows={3}
            value={history}
            placeholder="记录既往干预、材料、时间及资料来源。"
            onChange={(e) => setHistory(e.target.value)}
          />
        </Field>
      </div>
      {children}
      <div className="form-actions">
        <Button variant="primary" type="submit" busy={busy} icon="check">
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
export function RecordsPage() {
  const [query, setQuery] = useState(""),
    [status, setStatus] = useState(""),
    [search, setSearch] = useState(""),
    [creating, setCreating] = useState(false);
  const { data, loading, error, reload } = useLoad<Entity[]>(
    `/records?q=${encodeURIComponent(search)}&status=${status}`,
  );
  const { act, busy } = useAction();
  const { user } = useApp();
  return (
    <>
      <PageHeading
        eyebrow="ARTIFACT RECORDS"
        title="文物病历"
        description="保存现状、证据与专业判断，让每一处变化有迹可循。"
      >
        {["surveyor", "restorer", "admin"].includes(user.role) && (
          <Button
            variant="primary"
            icon="plus"
            onClick={() => setCreating(true)}
          >
            新建病历
          </Button>
        )}
      </PageHeading>
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query);
        }}
      >
        <div className="search-field">
          <Icon name="search" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文物名称、地区或病历编号"
            aria-label="搜索病历"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="病历状态"
        >
          <option value="">全部状态</option>
          {["draft", "review", "approved", "rejected"].map((s) => (
            <option key={s} value={s}>
              {statusNames[s]}
            </option>
          ))}
        </select>
        <Button type="submit">搜索</Button>
        <span className="filter-count">{data?.length ?? 0} 份病历</span>
      </form>
      <LoadState loading={loading} error={error} retry={reload}>
        {data?.length ? (
          <div className="record-grid">
            {data.map((item) => (
              <a
                className="record-card"
                key={item.id}
                href={`#records/${item.id}`}
              >
                <div className="record-cover">
                  {item.thumbnail_url ? (
                    <img
                      src={item.thumbnail_url}
                      alt={`${item.name}现状影像`}
                    />
                  ) : (
                    <div className="record-placeholder">
                      <Icon name="image" size={42} />
                      <span>等待现场影像</span>
                    </div>
                  )}
                  <span className="record-cover-badge">
                    <Badge value={item.status} />
                  </span>
                  {item.is_demo && (
                    <span className="demo-image-label">教学绘制样本</span>
                  )}
                </div>
                <div className="record-card-body">
                  <div className="record-card-meta">
                    <span>
                      {item.region || "地区待填写"} · {item.era || "年代待考"}
                    </span>
                    <span>v{item.version}</span>
                  </div>
                  <h2>{item.name}</h2>
                  <p>
                    {item.type || "文物调查"}{" "}
                    <span className="record-id">{item.id}</span>
                  </p>
                  <div className="record-card-footer">
                    <span>
                      <Icon name="image" size={15} />
                      {item.image_count || 0} 张影像
                    </span>
                    <span>
                      <Icon name="polygon" size={15} />
                      {item.disease_count || 0} 处标注
                    </span>
                    <Icon name="arrow" size={18} />
                  </div>
                </div>
              </a>
            ))}
          </div>
        ) : (
          <Panel>
            <Empty
              title={search ? "没有找到匹配的病历" : "建立第一份文物病历"}
              description={
                search
                  ? "可尝试其他名称或清除筛选条件。"
                  : "填写基本信息，上传现场影像，开始完整的保护记录。"
              }
            />
          </Panel>
        )}
      </LoadState>
      {creating && (
        <Modal title="新建文物病历" onClose={() => setCreating(false)}>
          <p className="muted">
            首批调查优先甘肃 / 敦煌。文物名称与现场位置按实际资料填写。
          </p>
          <RecordForm
            busy={busy}
            onSubmit={async (payload) => {
              const result = await act(
                () => post("/records", payload),
                "病历已建立",
              );
              if (result) {
                setCreating(false);
                location.hash = `records/${result.id}`;
              }
            }}
          />
        </Modal>
      )}
    </>
  );
}

export function KnowledgeCard({ item }: { item: Entity }) {
  return (
    <article className="knowledge-card">
      <div className="knowledge-meta">
        <Badge value={item.kind}>
          {(
            {
              standard: "国家 / 行业标准",
              case: "公开案例",
              article: "研究资料",
              guideline: "保护规范",
            } as Entity
          )[item.kind] ||
            item.kind ||
            "参考资料"}
        </Badge>
        {item.verified ? (
          <span className="verified">
            <Icon name="check" size={13} />
            来源已核对
          </span>
        ) : (
          <span className="muted">条款 / 适用性待核对</span>
        )}
      </div>
      <h3>{item.title}</h3>
      <p>{item.text || item.summary}</p>
      {item.standard && (
        <div className="reference-strip">
          {item.standard} {item.clause && `· ${item.clause}`}{" "}
          {item.version && `· ${item.version}`}
        </div>
      )}
      {item.match_reasons && (
        <p className="match-reasons">
          检索依据：
          {Array.isArray(item.match_reasons)
            ? item.match_reasons.join("；")
            : item.match_reasons}
        </p>
      )}
      {item.outcome && (
        <p>
          <b>公开报告的结果：</b>
          {item.outcome}
        </p>
      )}
      <div className="tags">
        {(item.tags || []).map((tag: string) => (
          <span key={tag}>{tag}</span>
        ))}
        {item.region && <span>{item.region}</span>}
      </div>
      <small className="muted">资料 ID：{item.id}</small>
      <Source item={item} />
    </article>
  );
}
export function KnowledgePage() {
  const [q, setQ] = useState(""),
    [kind, setKind] = useState(""),
    [region, setRegion] = useState(""),
    [disease, setDisease] = useState(""),
    [query, setQuery] = useState("");
  const { dict } = useApp();
  const { data, loading, error, reload } = useLoad<Entity>(
    `/knowledge?${query}`,
  );
  function search(e: FormEvent) {
    e.preventDefault();
    setQuery(new URLSearchParams({ q, kind, region, disease }).toString());
  }
  return (
    <>
      <PageHeading
        eyebrow="EVIDENCE LIBRARY"
        title="循证资料"
        description="优先整理中国国内的标准、保护研究与公开案例，保留来源和核验状态。"
      />
      <form className="filters wrap" onSubmit={search}>
        <div className="search-field">
          <Icon name="search" />
          <input
            aria-label="检索资料"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="检索标准编号、关键词或保护方法"
          />
        </div>
        <select
          aria-label="资料类型"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="">全部类型</option>
          <option value="standard">标准</option>
          <option value="case">案例</option>
          <option value="guideline">规范</option>
          <option value="article">研究资料</option>
        </select>
        <select
          aria-label="病害类别"
          value={disease}
          onChange={(e) => setDisease(e.target.value)}
        >
          <option value="">全部病害</option>
          {(dict.diseases || []).map((i: Entity) => (
            <option value={i.type} key={i.type}>
              {i.type}
            </option>
          ))}
        </select>
        <input
          className="short-input"
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          placeholder="地区，例如甘肃"
          aria-label="地区"
        />
        <Button type="submit" variant="primary">
          检索资料
        </Button>
      </form>
      <div className="callout compact">
        <Icon name="book" />
        公开摘要用于检索线索。标准元数据核验与全文条款核验分别记录；实际方案需核对原文与适用范围。
      </div>
      <LoadState loading={loading} error={error} retry={reload}>
        {data?.items?.length ? (
          <>
            <div className="results-label">
              检索到 {data.count ?? data.items.length} 条资料
            </div>
            <div className="knowledge-grid">
              {data.items.map((item: Entity) => (
                <KnowledgeCard key={item.id} item={item} />
              ))}
            </div>
          </>
        ) : (
          <Panel>
            <Empty
              title="没有找到匹配资料"
              description="减少筛选条件，或使用标准编号、地区与病害关键词检索。"
              icon="book"
            />
          </Panel>
        )}
      </LoadState>
    </>
  );
}

export function ReviewQueue() {
  const { data, loading, error, reload } = useLoad<Entity[]>("/consultations");
  return (
    <>
      <PageHeading
        eyebrow="EXPERT CONSULTATION"
        title="专家会诊"
        description="集中查看待审方案，结合病历、引用依据与规则检查进行专业审核。"
      />
      <div className="callout">
        <Icon name="people" />
        <div>
          <b>作者与审核人分离</b>
          <p>
            在病历的「会诊」工作区提出意见。最终审核需使用专家身份，绑定具体病历与方案版本。
          </p>
        </div>
      </div>
      <LoadState loading={loading} error={error} retry={reload}>
        <Panel
          title="方案审核队列"
          action={<Button onClick={reload}>刷新</Button>}
        >
          {data?.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>关联文物</th>
                    <th>方案版本</th>
                    <th>当前状态</th>
                    <th>提交 / 创建时间</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((item) => (
                    <tr key={item.plan_id || item.id}>
                      <td>
                        <b>{item.record_name || item.name}</b>
                        <small>{item.record_id}</small>
                      </td>
                      <td>v{item.version}</td>
                      <td>
                        <Badge value={item.status} />
                      </td>
                      <td>{fmtTime(item.submitted_at || item.created_at)}</td>
                      <td>
                        <a
                          href={`#records/${item.record_id}?tab=consultation`}
                          className="text-link"
                        >
                          进入会诊 <Icon name="arrow" size={15} />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="暂无待审核方案"
              description="方案通过阻断规则检查并提交后，将进入专家审核队列。"
              icon="people"
            />
          )}
        </Panel>
      </LoadState>
    </>
  );
}
export function AuditTable({ items }: { items: Entity[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return items.length ? (
    <div className="table-wrap">
      <table className="audit-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>操作人</th>
            <th>操作</th>
            <th>对象</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <AuditRow
              key={item.id || index}
              item={item}
              expanded={expanded === String(item.id || index)}
              toggle={() =>
                setExpanded(
                  expanded === String(item.id || index)
                    ? null
                    : String(item.id || index),
                )
              }
            />
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty
      title="尚无审计记录"
      description="创建、编辑、审核、下载等操作将在这里留痕。"
      icon="audit"
    />
  );
}
function AuditRow({
  item,
  expanded,
  toggle,
}: {
  item: Entity;
  expanded: boolean;
  toggle: () => void;
}) {
  return (
    <>
      <tr>
        <td>{fmtTime(item.created_at || item.timestamp)}</td>
        <td>
          {item.user_name ||
            item.username ||
            item.actor ||
            item.user_id ||
            "系统"}
        </td>
        <td>
          <span className="audit-action">{item.action}</span>
        </td>
        <td>
          {item.object_type}
          <small>{item.object_id || item.record_id}</small>
        </td>
        <td>
          <button className="text-button" onClick={toggle}>
            {expanded ? "收起" : "查看留痕"}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={5}>
            <pre className="json-view">{JSON.stringify(item, null, 2)}</pre>
          </td>
        </tr>
      )}
    </>
  );
}
export function AuditPage() {
  const [id, setId] = useState(""),
    [filter, setFilter] = useState("");
  const { data, loading, error, reload } = useLoad<Entity[]>(
    `/audit${filter ? "?record_id=" + encodeURIComponent(filter) : ""}`,
  );
  return (
    <>
      <PageHeading
        eyebrow="AUDIT TRAIL"
        title="审计日志"
        description="还原谁在何时，对哪一份记录进行了什么操作。"
      />
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setFilter(id);
        }}
      >
        <div className="search-field">
          <Icon name="search" />
          <input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="按完整病历编号筛选"
            aria-label="病历编号"
          />
        </div>
        <Button type="submit">筛选</Button>
        <Button onClick={reload} type="button">
          刷新
        </Button>
      </form>
      <LoadState loading={loading} error={error} retry={reload}>
        <Panel>
          <AuditTable items={data || []} />
        </Panel>
      </LoadState>
    </>
  );
}
export function SystemPage() {
  const health = useLoad<Entity>("/health"),
    readiness = useLoad<any>("/system/readiness");
  return (
    <>
      <PageHeading
        eyebrow="CAPABILITY & PROVENANCE"
        title="运行状态"
        description="明确区分已运行功能、可接入能力和仍需真实数据验证的指标。"
      />
      <LoadState
        loading={health.loading}
        error={health.error}
        retry={health.reload}
      >
        {health.data && (
          <Panel
            title="服务与模型状态"
            action={
              <Button
                onClick={() => {
                  health.reload();
                  readiness.reload();
                }}
              >
                刷新状态
              </Button>
            }
          >
            <div className="system-grid">
              {Object.entries(health.data).map(([key, value]) => (
                <div className="system-item" key={key}>
                  <span className="eyebrow">{key}</span>
                  <b>
                    {typeof value === "object"
                      ? value?.status || value?.provider || "详细状态"
                      : typeof value === "boolean"
                        ? value
                          ? "已启用"
                          : "未启用"
                        : String(value)}
                  </b>
                  {typeof value === "object" && (
                    <pre>{JSON.stringify(value, null, 2)}</pre>
                  )}
                </div>
              ))}
            </div>
          </Panel>
        )}
      </LoadState>
      <LoadState
        loading={readiness.loading}
        error={readiness.error}
        retry={readiness.reload}
      >
        <Panel title="功能就绪清单">
          {(Array.isArray(readiness.data)
            ? readiness.data
            : Array.isArray(readiness.data?.capabilities)
              ? readiness.data.capabilities
              : readiness.data?.items || []
          ).map((item: Entity, index: number) => (
            <div className="readiness-row" key={item.id || item.name || index}>
              <div>
                <b>{item.name || item.capability || item.id}</b>
                <p>
                  <Value
                    value={
                      item.description ||
                      item.detail ||
                      item.reason ||
                      item.notes
                    }
                  />
                </p>
                {item.limitations && (
                  <p className="muted">
                    <Value value={item.limitations} />
                  </p>
                )}
              </div>
              <Badge value={item.status}>
                {statusNames[item.status] ||
                  item.status ||
                  String(item.available ?? "未测定")}
              </Badge>
            </div>
          ))}
          {readiness.data &&
            !Array.isArray(readiness.data) &&
            !readiness.data?.capabilities &&
            !readiness.data?.items && (
              <pre className="json-view">
                {JSON.stringify(readiness.data, null, 2)}
              </pre>
            )}
        </Panel>
      </LoadState>
    </>
  );
}
