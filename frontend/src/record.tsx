import { useEffect, useState } from "react";
import {
  API,
  download,
  fmtTime,
  fmtNum,
  imageUrl,
  post,
  put,
  runJob,
  type Entity,
} from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  Icon,
  LoadState,
  PageHeading,
  Panel,
  useAction,
  useApp,
  useLoad,
  Value,
} from "./ui";
import { AuditTable, KnowledgeCard, RecordForm } from "./overview";
import AnnotationWorkspace from "./annotation";
import { ArchiveEntries, SensitiveExport } from "./archive";
import { ClinicalDataEditor } from "./clinical";
import { CaseEvidenceWorkspace } from "./cases";
import PlanWorkspace, { ConsultationWorkspace } from "./plans";
import { RecordWorkflow } from "./workflow";

const tabs = [
  ["images", "image", "影像与标注"],
  ["record", "record", "结构化病历"],
  ["evidence", "book", "病例与依据"],
  ["plans", "audit", "修复方案"],
  ["consultation", "people", "专家会诊"],
  ["simulation", "spark", "模拟与对比"],
  ["archive", "download", "档案归集"],
];
export default function RecordDetail({ id }: { id: string }) {
  const {
    data: record,
    loading,
    error,
    reload,
  } = useLoad<Entity>(`/records/${encodeURIComponent(id)}`);
  const [tab, setTab] = useState(
    new URLSearchParams(location.hash.split("?")[1] || "").get("tab") ||
      "images",
  );
  const navigateTab = (next: string) => {
    setTab(next);
    window.history.replaceState(null, "", `#records/${id}?tab=${next}`);
  };
  useEffect(() => {
    const sync = () =>
      setTab(
        new URLSearchParams(location.hash.split("?")[1] || "").get("tab") ||
          "images",
      );
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  return (
    <LoadState loading={loading && !record} error={error} retry={reload}>
      {record && (
        <>
          <div className="record-back">
            <a href="#records">← 返回文物病历</a>
            <span>{record.id}</span>
          </div>
          <PageHeading
            eyebrow="ARTIFACT HEALTH RECORD"
            title={record.artifact?.name || "未命名病历"}
            description={`${record.artifact?.region || "地区待填写"} / ${record.artifact?.type || "类型待填写"} / ${record.artifact?.era || "年代待考"}`}
          >
            <Badge value={record.status} />
            <span className="version-tag">病历 v{record.version}</span>
            {record.is_demo && (
              <Badge value="warn">教学示例 · 非真实文物</Badge>
            )}
            {record.artifact?.record_kind === "public_reference" && (
              <Badge value="neutral">公开馆藏参考 · 非现场调查</Badge>
            )}
          </PageHeading>
          <div className="record-overview">
            <div>
              <span>调查日期</span>
              <b>{record.survey?.date || "未填写"}</b>
            </div>
            <div>
              <span>保存位置</span>
              <b>{record.artifact?.location || "未填写"}</b>
            </div>
            <div>
              <span>采集影像</span>
              <b>
                {record.images?.length || 0}
                <small> 张</small>
              </b>
            </div>
            <div>
              <span>病害标注</span>
              <b>
                {record.diseases?.length || 0}
                <small> 处</small>
              </b>
            </div>
            <div>
              <span>最近更新</span>
              <b>{fmtTime(record.updated_at || record.created_at)}</b>
            </div>
          </div>
          <RecordWorkflow record={record} onNavigate={navigateTab} />
          <nav className="workspace-tabs" aria-label="病历工作区">
            {tabs.map(([key, icon, title]) => (
              <button
                key={key}
                className={tab === key ? "active" : ""}
                onClick={() => navigateTab(key)}
              >
                <Icon name={icon} size={17} />
                {title}
              </button>
            ))}
          </nav>
          {tab === "images" ? (
            <AnnotationWorkspace record={record} reload={reload} />
          ) : tab === "record" ? (
            <ClinicalRecord record={record} reload={reload} />
          ) : tab === "evidence" ? (
            <CaseEvidenceWorkspace record={record} reload={reload} />
          ) : tab === "plans" ? (
            <PlanWorkspace record={record} reload={reload} />
          ) : tab === "consultation" ? (
            <ConsultationWorkspace record={record} reload={reload} />
          ) : tab === "simulation" ? (
            <SimulationWorkspace record={record} reload={reload} />
          ) : (
            <ArchiveWorkspace record={record} reload={reload} />
          )}
        </>
      )}
    </LoadState>
  );
}

function ClinicalRecord({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { user } = useApp();
  const { act, busy } = useAction();
  const [draft, setDraft] = useState<Entity>(record),
    [diagnosis, setDiagnosis] = useState<Entity>(record.diagnosis || {}),
    [clinicalData, setClinicalData] = useState<Entity>(
      record.clinical_data || {},
    ),
    [extractText, setExtractText] = useState(""),
    [includeExtractImage, setIncludeExtractImage] = useState(false),
    [extractImageId, setExtractImageId] = useState(
      String(record.images?.[0]?.id || ""),
    ),
    [extracted, setExtracted] = useState<Entity | null>(null),
    [formVersion, setFormVersion] = useState(0);
  const editable = ["surveyor", "restorer", "admin"].includes(user.role);
  useEffect(() => {
    setDraft(record);
    setDiagnosis(record.diagnosis || {});
    setClinicalData(record.clinical_data || {});
    setFormVersion((v) => v + 1);
  }, [record.version]);
  async function extract() {
    const value = await act(
      () =>
        post(`/records/${record.id}/extract`, {
          text: extractText,
          ...(includeExtractImage && extractImageId
            ? { image_id: extractImageId }
            : {}),
        }),
      "抽取结果已生成，核对后可载入编辑表单。",
    );
    if (value) setExtracted(value);
  }
  return (
    <div className="clinical-layout">
      <div>
        <Panel title="结构化调查记录" eyebrow="SURVEY & HISTORY">
          {editable ? (
            <RecordForm
              key={formVersion}
              initial={draft}
              busy={busy}
              submitLabel="保存病历与诊断"
              onSubmit={(payload) =>
                act(async () => {
                  await put(`/records/${record.id}`, {
                    ...payload,
                    diagnosis,
                    clinical_data: clinicalData,
                    expected_version: record.version,
                  });
                  reload();
                }, "病历已更新；关联方案需要重新核对当前版本")
              }
            >
              <ClinicalDataEditor
                value={clinicalData}
                onChange={setClinicalData}
              />
            </RecordForm>
          ) : (
            <>
              <div className="form-grid">
                {Object.entries({ ...record.artifact, ...record.survey }).map(
                  ([key, value]) => (
                    <div className="read-field" key={key}>
                      <span>
                        {(
                          {
                            name: "文物名称",
                            type: "类型",
                            era: "年代",
                            region: "地区",
                            location: "位置",
                            area_m2: "调查面积 m²",
                            support_type: "支撑体",
                            ground_type: "地仗层",
                            pigment_type: "颜料类型",
                            date: "调查日期",
                            weather: "天气",
                            light: "光照条件",
                            equipment: "采集设备",
                            humidity: "相对湿度 %",
                            water_leak: "是否渗水",
                          } as Entity
                        )[key] || key}
                      </span>
                      <b>
                        <Value value={value} />
                      </b>
                    </div>
                  ),
                )}
              </div>
              <h3>现状主诉</h3>
              <p>{record.chief_complaint || "未记录"}</p>
              <h3>保护历史</h3>
              <p>{record.history || "未记录"}</p>
              <ClinicalDataEditor
                value={record.clinical_data || {}}
                onChange={() => {}}
                disabled
              />
            </>
          )}
        </Panel>
      </div>
      <div>
        <Panel title="诊断假设与证据">
          <Field label="诊断假设">
            <textarea
              disabled={!editable}
              rows={5}
              value={diagnosis.hypothesis || ""}
              onChange={(e) =>
                setDiagnosis({ ...diagnosis, hypothesis: e.target.value })
              }
              placeholder="区分观察事实、可能机制与仍待验证的假设。"
            />
          </Field>
          <Field label="依据清单（每行一项）">
            <textarea
              disabled={!editable}
              rows={4}
              value={(diagnosis.evidence || []).join("\n")}
              onChange={(e) =>
                setDiagnosis({
                  ...diagnosis,
                  evidence: e.target.value.split("\n").filter(Boolean),
                })
              }
              placeholder="检测记录、标准条文、历史档案或公开案例。"
            />
          </Field>
          <Field label="不确定性与下一步核查">
            <textarea
              disabled={!editable}
              rows={4}
              value={diagnosis.uncertainty || ""}
              onChange={(e) =>
                setDiagnosis({ ...diagnosis, uncertainty: e.target.value })
              }
              placeholder="例如：缺少含水率与可溶盐检测结果。"
            />
          </Field>
          <p className="muted">以上诊断随左侧「保存病历与诊断」一起保存。</p>
        </Panel>
        {editable && (
          <Panel
            title="调查资料辅助抽取"
            action={<Icon name="spark" size={18} />}
          >
            <Field label="原始调查文字">
              <textarea
                rows={5}
                value={extractText}
                onChange={(e) => setExtractText(e.target.value)}
                placeholder="粘贴现场笔记或历史档案摘录，保留原始信息与出处。"
              />
            </Field>
            <label className="check-field">
              <input
                type="checkbox"
                checked={includeExtractImage}
                disabled={!record.images?.length}
                onChange={(e) => setIncludeExtractImage(e.target.checked)}
              />
              同时读取当前影像／档案图
            </label>
            {includeExtractImage && (
              <>
                <Field label="用于抽取的影像／档案图">
                  <select
                    value={extractImageId}
                    onChange={(e) => setExtractImageId(e.target.value)}
                  >
                    {(record.images || []).map((img: Entity) => (
                      <option key={img.id} value={img.id}>
                        {img.filename} ·{" "}
                        {img.image_type === "document"
                          ? "档案图"
                          : img.image_type === "followup"
                            ? "复查影像"
                            : "现状影像"}
                      </option>
                    ))}
                  </select>
                </Field>
                <p className="muted">
                  仅选择的影像用于本次请求。服务端将长边缩至不超过 1600
                  像素；配置视觉模型并授权外发后才调用。未配置时仅保留文字整理草稿，影像未被模型读取。
                </p>
              </>
            )}
            {!record.images?.length && (
              <p className="muted">
                上传现状影像或档案图后，可选择同时提取影像信息。
              </p>
            )}
            <p className="muted">
              抽取结果不会自动覆盖病历，须核对并载入表单后另行保存。
            </p>
            <Button
              variant="secondary full"
              busy={busy}
              disabled={
                !extractText.trim() || (includeExtractImage && !extractImageId)
              }
              onClick={extract}
            >
              抽取为病历草稿
            </Button>
            {extracted && (
              <div className="extraction-preview">
                <Badge value={extracted.provider} />
                <small>模型：{extracted.model_version || "无模型调用"}</small>
                <h3>建议主诉</h3>
                <p>{extracted.chief_complaint || "无抽取结果"}</p>
                <h3>建议诊断</h3>
                <p>{extracted.diagnosis?.hypothesis || "无抽取结果"}</p>
                {extracted.uncertainty && (
                  <p className="muted">{extracted.uncertainty}</p>
                )}
                <details>
                  <summary>完整结构化结果</summary>
                  <pre>{JSON.stringify(extracted, null, 2)}</pre>
                </details>
                <Button
                  onClick={() => {
                    setDraft({
                      ...draft,
                      chief_complaint:
                        extracted.chief_complaint ?? draft.chief_complaint,
                      history: extracted.history ?? draft.history,
                    });
                    setDiagnosis(extracted.diagnosis || diagnosis);
                    setFormVersion((v) => v + 1);
                  }}
                >
                  核对后载入表单（尚未保存）
                </Button>
              </div>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}

function SimulationWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { dict, user } = useApp(),
    { act, busy } = useAction();
  const images: Entity[] = record.images || [];
  const jobs = useLoad<Entity[]>(`/records/${record.id}/jobs`);
  const [imageId, setImageId] = useState(String(images[0]?.id || "")),
    [afterId, setAfterId] = useState(
      String(
        images.find((i) => i.image_type === "followup")?.id ||
          images[1]?.id ||
          "",
      ),
    ),
    [types, setTypes] = useState<string[]>([]),
    [result, setResult] = useState<Entity | null>(null),
    [status, setStatus] = useState(""),
    [resultKind, setResultKind] = useState("simulate"),
    [split, setSplit] = useState(50),
    [showUncertainty, setShowUncertainty] = useState(false);
  const img = images.find((i) => String(i.id) === imageId);
  const resultImage = images.find(
    (image) =>
      String(image.id) === String(result?.image_id || result?.before_image_id),
  );
  const savedJobs: Entity[] = [
    ...[...(record.simulations || [])]
      .reverse()
      .map((item: Entity) => ({ ...item, kind: "simulate", result: item })),
    ...(jobs.data || [])
      .filter((job) => job.kind === "comparison" && job.status === "completed")
      .map((job) => ({ ...job, kind: "compare" })),
  ];
  const editable = ["restorer", "expert", "admin"].includes(user.role);
  async function run(kind: string) {
    setResult(null);
    setResultKind(kind);
    const data = await act(
      () =>
        runJob(
          `/records/${record.id}/${kind}`,
          kind === "simulate"
            ? { image_id: imageId, types }
            : { before_image_id: imageId, after_image_id: afterId },
          (job) => setStatus(job.status),
        ),
      kind === "simulate"
        ? "教学模拟已生成，原始影像保持不变"
        : "影像对比任务已完成",
    );
    setStatus("");
    if (data) {
      setResult(data);
      setShowUncertainty(false);
      jobs.reload();
      reload();
    }
  }
  return (
    <>
      <div className="callout amber">
        <Icon name="warning" />
        <div>
          <b>预览效果不等于修复结果</b>
          <p>
            模拟图独立存储并带水印，仅帮助交流，不作为真实文物影像。跨时间影像未配准时，不推断真实病害增减。
          </p>
        </div>
      </div>
      {!images.length ? (
        <Panel>
          <Empty
            title="先上传现场影像"
            description="至少需要一张影像进行模拟，两张影像进行前后对比。"
            icon="image"
          />
        </Panel>
      ) : (
        <>
          <div className="two-column">
            <Panel title="术前教学模拟" eyebrow="WATERMARKED PREVIEW">
              <Field label="选择原始影像">
                <select
                  value={imageId}
                  onChange={(e) => setImageId(e.target.value)}
                >
                  {images.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.filename}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="拟讨论的病害类型">
                <div className="checkbox-grid">
                  {(dict.diseases || []).map((d: Entity) => (
                    <label className="check-field" key={d.type}>
                      <input
                        type="checkbox"
                        checked={types.includes(d.type)}
                        onChange={(e) =>
                          setTypes((old) =>
                            e.target.checked
                              ? [...old, d.type]
                              : old.filter((v) => v !== d.type),
                          )
                        }
                      />
                      {d.type}
                    </label>
                  ))}
                </div>
              </Field>
              <p className="muted">
                按已保存标注生成局部视觉模拟，并保留模型 / 方法与局限说明。
              </p>
              <Button
                variant="primary"
                busy={busy && resultKind === "simulate"}
                disabled={busy || !editable}
                onClick={() => run("simulate")}
                icon="spark"
              >
                生成带水印模拟
              </Button>
            </Panel>
            <Panel title="前后影像对比" eyebrow="FOLLOW-UP COMPARISON">
              <Field label="基线影像">
                <select
                  value={imageId}
                  onChange={(e) => setImageId(e.target.value)}
                >
                  {images.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.filename}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="复查 / 对比影像">
                <select
                  value={afterId}
                  onChange={(e) => setAfterId(e.target.value)}
                >
                  <option value="">请选择另一张影像</option>
                  {images
                    .filter((i) => String(i.id) !== imageId)
                    .map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.filename}
                      </option>
                    ))}
                </select>
              </Field>
              <p className="muted">
                系统返回配准与差异结果；对比指标需结合光照、拍摄角度和现场记录解释。
              </p>
              <Button
                busy={busy && resultKind === "compare"}
                disabled={busy || !afterId || afterId === imageId || !editable}
                onClick={() => run("compare")}
                icon="image"
              >
                运行影像对比
              </Button>
            </Panel>
          </div>
          {status && (
            <div className="callout">
              <span className="spinner small" />
              任务处理中：{status}
            </div>
          )}
          {result && (
            <Panel
              title={
                resultKind === "simulate"
                  ? "模拟预览 · 非原始影像"
                  : "影像对比结果"
              }
              action={
                <Badge value="warn">{result.watermark || "仅供辅助讨论"}</Badge>
              }
            >
              <div className="result-provenance">
                <span>原始影像：{resultImage?.filename || "来源未记录"}</span>
                {result.source_record_version !== undefined && (
                  <span>来源病历 v{result.source_record_version}</span>
                )}
                {result.source_record_version !== undefined &&
                  result.source_record_version !== record.version && (
                    <Badge value="warn">历史输入 · 当前病历已更新</Badge>
                  )}
                {result.source_polygons && (
                  <span>{result.source_polygons.length} 个保存的推测区域</span>
                )}
              </div>
              {resultKind === "simulate" && result.uncertainty_url && (
                <label className="check-field uncertainty-toggle">
                  <input
                    type="checkbox"
                    checked={showUncertainty}
                    onChange={(e) => setShowUncertainty(e.target.checked)}
                  />
                  在原图上查看不确定区域
                </label>
              )}
              {result.url && resultImage ? (
                <>
                  <div className="image-comparison">
                    <img src={imageUrl(resultImage)} alt="原始影像" />
                    <div
                      className="image-comparison-overlay"
                      style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
                    >
                      <img
                        src={
                          showUncertainty ? result.uncertainty_url : result.url
                        }
                        alt={
                          showUncertainty
                            ? "模拟不确定区域"
                            : "带水印教学模拟影像"
                        }
                      />
                    </div>
                    <div
                      className="comparison-divider"
                      style={{ left: `${split}%` }}
                    />
                    <span className="comparison-label left">
                      {showUncertainty ? "推测区域" : "模拟预览"}
                    </span>
                    <span className="comparison-label right">原始影像</span>
                  </div>
                  <label className="compare-slider">
                    拖动对比
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={split}
                      onChange={(e) => setSplit(Number(e.target.value))}
                    />
                  </label>
                </>
              ) : result.comparison_url ? (
                <img
                  className="result-image"
                  src={result.comparison_url}
                  alt="前后影像对比结果"
                />
              ) : null}
              <div className="result-explanation">
                <p>
                  <b>方法：</b>
                  <Value value={result.method} />
                </p>
                <p>
                  <b>局限：</b>
                  <Value value={result.limitations} />
                </p>
                {result.uncertainty_type && (
                  <div className="callout compact amber">
                    {result.uncertainty_type}
                  </div>
                )}
                {resultKind === "compare" && (
                  <>
                    <Badge value={result.alignment_success ? "ready" : "warn"}>
                      {result.alignment_success
                        ? "影像已自动配准 · 需复核"
                        : "配准未成功 · 不计算变化量"}
                    </Badge>
                    <div className="measurement-grid">
                      {[
                        ["overlap_fraction", "共同可见区域", true],
                        [
                          "mean_absolute_pixel_difference",
                          "平均像素绝对差",
                          false,
                        ],
                        [
                          "changed_fraction_at_25_gray",
                          "可视化差异区域比例",
                          true,
                        ],
                        ["inlier_matches", "一致性匹配点", false],
                      ].map(([key, label, percent]) => (
                        <div key={String(key)}>
                          <span>{label}</span>
                          <b>
                            {result[String(key)] == null
                              ? "未计算"
                              : `${fmtNum(result[String(key)] * (percent ? 100 : 1))}${percent ? "%" : ""}`}
                          </b>
                        </div>
                      ))}
                    </div>
                    <p className="muted">
                      {result.change_threshold_note ||
                        "没有经标定的病害变化阈值。"}
                    </p>
                    {result.aligned_image && (
                      <details>
                        <summary>查看配准后的复查影像</summary>
                        <img
                          className="result-image"
                          src={result.aligned_image}
                          alt="配准后的复查影像"
                        />
                      </details>
                    )}
                  </>
                )}
                {result.metrics && (
                  <pre className="json-view">
                    {JSON.stringify(result.metrics, null, 2)}
                  </pre>
                )}
                {result.uncertainty_url && (
                  <details>
                    <summary>查看不确定性区域</summary>
                    <img
                      className="result-image"
                      src={result.uncertainty_url}
                      alt="模拟不确定性区域图"
                    />
                  </details>
                )}
                <details>
                  <summary>查看完整任务记录</summary>
                  <pre>{JSON.stringify(result, null, 2)}</pre>
                </details>
              </div>
            </Panel>
          )}
          <Panel
            title="已保存的模拟 / 对比任务"
            action={
              <Button
                onClick={() => {
                  jobs.reload();
                  reload();
                }}
              >
                刷新任务历史
              </Button>
            }
          >
            <LoadState
              loading={jobs.loading}
              error={jobs.error}
              retry={jobs.reload}
            >
              {savedJobs.length ? (
                <div className="saved-simulations">
                  {savedJobs.map((item: Entity) => (
                    <button
                      key={`${item.kind}-${item.id}`}
                      className="simulation-card"
                      onClick={() => {
                        const selectedResult = item.result || item;
                        setResult(selectedResult);
                        setResultKind(item.kind);
                        setShowUncertainty(false);
                        if (
                          selectedResult.image_id ||
                          selectedResult.before_image_id
                        )
                          setImageId(
                            String(
                              selectedResult.image_id ||
                                selectedResult.before_image_id,
                            ),
                          );
                        if (selectedResult.after_image_id)
                          setAfterId(String(selectedResult.after_image_id));
                      }}
                    >
                      {(item.result?.url || item.result?.comparison_url) && (
                        <img
                          src={item.result.url || item.result.comparison_url}
                          alt={
                            item.kind === "compare"
                              ? "前后对比记录"
                              : "带水印模拟记录"
                          }
                        />
                      )}
                      <b>
                        {item.kind === "compare"
                          ? "前后影像对比"
                          : "术前教学模拟"}
                      </b>
                      <span>{fmtTime(item.created_at)}</span>
                      <small>{item.result?.method || "方法未记录"}</small>
                    </button>
                  ))}
                </div>
              ) : (
                <Empty title="尚无已完成的模拟或对比任务" />
              )}
              {(jobs.data || [])
                .filter(
                  (job) =>
                    ["simulation", "comparison"].includes(job.kind) &&
                    job.status !== "completed",
                )
                .map((job) => (
                  <div className="job-history-row" key={job.id}>
                    <span>
                      {job.kind === "simulation" ? "模拟" : "对比"} ·{" "}
                      {fmtTime(job.created_at)}
                    </span>
                    <Badge value={job.status} />
                    {job.error && (
                      <span>
                        {typeof job.error === "string"
                          ? job.error
                          : JSON.stringify(job.error)}
                      </span>
                    )}
                  </div>
                ))}
            </LoadState>
          </Panel>
        </>
      )}
    </>
  );
}

function ArchiveWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { act, busy } = useAction();
  const [preview, setPreview] = useState(false);
  return (
    <>
      <div className="workspace-actions">
        <div>
          <h2>归集每一次保护的依据</h2>
          <p className="muted">
            归档包含病历、标注、方案版本与会诊记录，下载行为写入审计。
          </p>
        </div>
      </div>
      <SensitiveExport record={record} />
      <div className="archive-grid">
        {[
          ["pdf", "PDF 病历档案", "便于阅读、审阅与线下留存。", "record"],
          ["json", "结构化 JSON", "保留字段、坐标、版本与来源。", "book"],
          ["zip", "完整归档 ZIP", "集中保存归档数据与相关文件。", "download"],
        ].map(([extension, title, desc, icon]) => (
          <Panel key={extension}>
            <div className="archive-icon">
              <Icon name={icon} size={25} />
            </div>
            <h3>{title}</h3>
            <p className="muted">{desc}</p>
            <Button
              variant="secondary full"
              busy={busy}
              icon="download"
              onClick={() =>
                act(
                  () =>
                    download(
                      `/records/${record.id}/archive.${extension}`,
                      `${record.id}-archive.${extension}`,
                    ),
                  `${title}已导出`,
                )
              }
            >
              导出 {extension.toUpperCase()}
            </Button>
          </Panel>
        ))}
      </div>
      <div className="callout">
        <Icon name="audit" />
        <div>
          <b>原始影像与模拟结果分别归档</b>
          <p>
            模拟图片不会覆盖现场原图。每个方案保留所绑定的病历版本，审核记录绑定具体内容。
          </p>
        </div>
      </div>
      <ArchiveEntries record={record} reload={reload} />
      <Panel title="原始与复查影像目录">
        {record.images?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>类型</th>
                  <th>原始尺寸</th>
                  <th>上传时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {record.images.map((img: Entity) => (
                  <tr key={img.id}>
                    <td>{img.filename}</td>
                    <td>
                      {(
                        {
                          original: "原始影像",
                          followup: "复查影像",
                          document: "资料影像",
                        } as Entity
                      )[img.image_type] || img.image_type}
                    </td>
                    <td>
                      {img.width} × {img.height}
                    </td>
                    <td>{fmtTime(img.created_at)}</td>
                    <td>
                      <Button
                        busy={busy}
                        onClick={() =>
                          act(
                            () =>
                              download(
                                `${API}/images/${img.id}/original`,
                                img.filename,
                              ),
                            "原始影像已下载",
                          )
                        }
                      >
                        下载原图
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="尚无影像" icon="image" />
        )}
      </Panel>
      <Panel
        title="当前病历内容"
        action={
          <Button onClick={() => setPreview(!preview)}>
            {preview ? "收起" : "查看 JSON"}
          </Button>
        }
      >
        {preview ? (
          <pre className="json-view">{JSON.stringify(record, null, 2)}</pre>
        ) : (
          <p className="muted">
            可检查结构化字段、病害原图坐标、方案来源与当前版本。
          </p>
        )}
      </Panel>
      <Panel title="本病历审计轨迹">
        <AuditTable items={record.audit || []} />
      </Panel>
    </>
  );
}
