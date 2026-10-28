import { useEffect, useState } from "react";
import { ApiError, download, fmtTime, post, put, type Entity } from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  Icon,
  Panel,
  Source,
  useAction,
  useApp,
  useLoad,
} from "./ui";

import { MeasuresEditor, BudgetEditor } from "./plan-structure";

function contentOf(section: any) {
  return typeof section === "string" ? section : section?.content || "";
}
function citationText(citation: any) {
  return typeof citation === "string"
    ? citation
    : citation.title ||
        citation.id ||
        citation.standard ||
        JSON.stringify(citation);
}
export function CheckResults({ check }: { check: any }) {
  const rows = Array.isArray(check) ? check : check?.items || [];
  return rows.length ? (
    <div className="rule-results">
      {!Array.isArray(check) && (
        <div className="rule-summary">
          <Badge value={check.overall} />
          <span>规则版本：{check.rules_version || "未记录"}</span>
        </div>
      )}
      {rows.map((item: Entity, index: number) => (
        <div className={`rule-row ${item.result}`} key={item.rule_id || index}>
          <span className="rule-icon">
            <Icon
              name={item.result === "pass" ? "check" : "warning"}
              size={17}
            />
          </span>
          <div>
            <b>
              {item.name || item.rule_id}
              <small>{item.rule_id}</small>
            </b>
            <p>{item.message || item.description || "未触发当前检查条件"}</p>
            {item.basis && (
              <small>
                依据：
                {typeof item.basis === "string"
                  ? item.basis
                  : JSON.stringify(item.basis)}{" "}
                {item.basis_status && `· ${item.basis_status}`}
              </small>
            )}
            {item.source_url&&<Source item={{title:"查看适用条款原文",source_url:item.source_url}}/>}
            {item.scope&&<small>适用范围：{item.scope==="flaking_adhesive_test"?"起甲粘接材料筛选试验":item.scope==="flaking_site_trial"?"起甲保护现场小试":item.scope}</small>}
          </div>
          <Badge value={item.result} />
        </div>
      ))}
    </div>
  ) : (
    <Empty
      title="尚未运行规则检查"
      description="检查章节完整性、依据、环境、材料与风险，结果保留规则版本。"
      icon="audit"
    />
  );
}
export default function PlanWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { user, dict } = useApp(),
    { act, busy } = useAction();
  const knowledge = useLoad<Entity>("/knowledge");
  const plans: Entity[] = [...(record.plans || [])].sort(
    (a, b) => b.version - a.version,
  );
  const [selectedId, setSelectedId] = useState(""),
    [editing, setEditing] = useState(false),
    [sections, setSections] = useState<Entity>({}),
    [currentKey, setCurrentKey] = useState(""),
    [compareId, setCompareId] = useState(""),
    [comparing, setComparing] = useState(false),
    [onlyChanged, setOnlyChanged] = useState(true),
    [check, setCheck] = useState<any>(null),
    [useLLM, setUseLLM] = useState(false);
  const plan = plans.find((p) => String(p.id) === selectedId) || plans[0],
    other = plans.find((p) => String(p.id) === compareId) || plans[1];
  const resolveCitation = (citation: any) =>
    typeof citation === "string"
      ? (plan?.evidence_snapshot || []).find(
          (item: Entity) => item.id === citation,
        ) ||
        (record.evidence_sources || []).find(
          (item: Entity) => item.id === citation,
        ) ||
        knowledge.data?.items?.find((item: Entity) => item.id === citation) || {
          id: citation,
        }
      : citation;
  const sourceKind = (item: Entity) =>
    (
      ({
        standard: "标准规范",
        case: "保护病例",
        expert: "专家意见",
        expert_note: "专家意见",
        research: "研究文献",
        rule: "规则依据",
      }) as Entity
    )[item.kind] || "资料依据";
  const editable = ["restorer", "admin"].includes(user.role);
  const canRevise =
    editable &&
    plan?.id === plans[0]?.id &&
    plan?.record_version === record.version;
  useEffect(() => {
    if (plan) {
      setSections(structuredClone(plan.sections || {}));
      setCurrentKey(Object.keys(plan.sections || {})[0] || "");
      setCheck(plan.checks || null);
    }
    setEditing(false);
  }, [plan?.id]);
  const keys = Object.keys(sections).sort(
    (a, b) => Number(a.split(".")[1]) - Number(b.split(".")[1]),
  );
  const section = sections[currentKey];
  async function generate() {
    const value = await act(
      () => post(`/records/${record.id}/plans`, { use_llm: useLLM }),
      "方案草案已生成，请逐章核对与补充证据。",
    );
    if (value) {
      setSelectedId(String(value.id));
      reload();
    }
  }
  async function save() {
    const value = await act(
      () =>
        put(`/plans/${plan.id}`, { expected_version: plan.version, sections }),
      "修订已另存为新版本，原版本保留",
    );
    if (value) {
      setSelectedId(String(value.id));
      setEditing(false);
      reload();
    }
  }
  async function checkPlan() {
    const value = await act(
      () => post(`/plans/${plan.id}/check`),
      "规则检查已完成",
    );
    if (value) setCheck(value);
  }
  return (
    <>
      <div className="workspace-actions">
        <div>
          <h2>循证修复方案</h2>
          <p className="muted">13 章结构草案 · 引用可追溯 · 修订保留历史版本</p>
        </div>
        <div className="inline-actions">
          {editable && (
            <>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={useLLM}
                  onChange={(e) => setUseLLM(e.target.checked)}
                />
                使用已配置大模型
              </label>
              <Button
                variant="primary"
                icon="spark"
                busy={busy}
                onClick={generate}
              >
                {plans.length ? "重新生成草案" : "生成方案草案"}
              </Button>
            </>
          )}
        </div>
      </div>
      {!editable && (
        <div className="callout compact">
          方案起草与修订由修复师负责。可通过左侧「切换身份」进入相应工作角色。
        </div>
      )}
      {!plan ? (
        <Panel>
          <Empty
            title="先把证据变成方案的基础"
            description="完善病历与病害标注后，由修复师生成 13 章方案草案；未接入大模型时使用明确标记的结构模板。"
            icon="book"
          />
        </Panel>
      ) : (
        <>
          <div className="plan-version-bar">
            <Field label="当前方案版本">
              <select
                value={plan.id}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    v{p.version} · {p.status} · {fmtTime(p.created_at)}
                  </option>
                ))}
              </select>
            </Field>
            <div className="plan-provenance">
              <Badge value={plan.status} />
              <span>病历 v{plan.record_version}</span>
              <span>来源：{plan.provider || "未记录"}</span>
              <span>模型：{plan.model_version || "无模型调用"}</span>
            </div>
            <div className="inline-actions">
              <Button
                disabled={plans.length < 2 || editing}
                onClick={() => setComparing(!comparing)}
              >
                {comparing ? "关闭对比" : "版本对比"}
              </Button>
              <Button
                icon="download"
                busy={busy}
                onClick={() =>
                  act(
                    () =>
                      download(
                        `/plans/${plan.id}/export.pdf`,
                        `${record.id}-plan-v${plan.version}.pdf`,
                      ),
                    "方案 PDF 已导出",
                  )
                }
              >
                导出 PDF
              </Button>
            </div>
          </div>
          {plan.provider === "template_fallback" && (
            <div className="callout compact amber">
              <Icon name="warning" />
              {plan.generation_note ||
                "当前为结构模板生成，未调用大模型。待填写内容与证据缺口须经修复师补充。"}
            </div>
          )}
          {plan.record_version !== record.version && (
            <div className="callout compact amber">
              <Icon name="warning" />
              本方案绑定病历 v{plan.record_version}，当前病历为 v
              {record.version}。应基于最新病历重新生成草案并审核。
            </div>
          )}
          {comparing && other ? (
            <Panel
              title="方案版本对比"
              action={
                <div className="inline-actions">
                  <select
                    aria-label="对比历史版本"
                    value={other.id}
                    onChange={(e) => setCompareId(e.target.value)}
                  >
                    {plans
                      .filter((p) => p.id !== plan.id)
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          v{p.version}
                        </option>
                      ))}
                  </select>
                  <label className="check-field">
                    <input
                      type="checkbox"
                      checked={onlyChanged}
                      onChange={(e) => setOnlyChanged(e.target.checked)}
                    />
                    仅看有修改章节
                  </label>
                </div>
              }
            >
              <div className="diff-head">
                <b>历史版本 v{other.version}</b>
                <b>当前版本 v{plan.version}</b>
              </div>
              {Array.from(
                new Set([...Object.keys(other.sections || {}), ...keys]),
              )
                .filter(
                  (key) =>
                    !onlyChanged ||
                    JSON.stringify(other.sections?.[key]) !==
                      JSON.stringify(sections[key]),
                )
                .map((key) => (
                  <div className="diff-row" key={key}>
                    <h3>
                      {key}{" "}
                      {sections[key]?.title || other.sections?.[key]?.title}
                    </h3>
                    <div>
                      <pre>
                        {contentOf(other.sections?.[key]) ||
                          "（该版本无此章节）"}
                      </pre>
                      <pre>
                        {contentOf(sections[key]) || "（该版本无此章节）"}
                      </pre>
                    </div>
                    {(JSON.stringify(other.sections?.[key]?.measures) !==
                      JSON.stringify(sections[key]?.measures) ||
                      JSON.stringify(other.sections?.[key]?.budget_items) !==
                        JSON.stringify(sections[key]?.budget_items) ||
                      JSON.stringify(other.sections?.[key]?.citations) !==
                        JSON.stringify(sections[key]?.citations) ||
                      other.sections?.[key]?.uncertainty !==
                        sections[key]?.uncertainty) && (
                      <details>
                        <summary>工序、预算、引用及不确定性差异</summary>
                        <div className="diff-extra">
                          {[other.sections?.[key], sections[key]].map(
                            (entry, index) => (
                              <pre key={index}>
                                {JSON.stringify(
                                  {
                                    measures: entry?.measures,
                                    budget_items: entry?.budget_items,
                                    citations: entry?.citations,
                                    uncertainty: entry?.uncertainty,
                                  },
                                  null,
                                  2,
                                )}
                              </pre>
                            ),
                          )}
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              {onlyChanged &&
                keys.every(
                  (key) =>
                    JSON.stringify(other.sections?.[key]) ===
                    JSON.stringify(sections[key]),
                ) && (
                  <p className="muted">
                    两个版本的章节正文、工序、预算和引用没有变化。
                  </p>
                )}
            </Panel>
          ) : (
            <div className="plan-layout">
              <nav className="chapter-nav">
                <span className="eyebrow">方案章节</span>
                {keys.map((key) => (
                  <button
                    key={key}
                    onClick={() => setCurrentKey(key)}
                    className={currentKey === key ? "active" : ""}
                  >
                    <span>{key}</span>
                    {sections[key]?.title ||
                      dict.plan_sections?.find((s: Entity) => s.key === key)
                        ?.title ||
                      "未命名章节"}
                  </button>
                ))}
              </nav>
              <Panel
                className="chapter-content"
                title={`${currentKey} ${section?.title || ""}`}
                action={
                  editable ? (
                    <div className="inline-actions">
                      {editing ? (
                        <>
                          <Button
                            onClick={() => {
                              setSections(structuredClone(plan.sections));
                              setEditing(false);
                            }}
                          >
                            取消修改
                          </Button>
                          <Button variant="primary" busy={busy} onClick={save}>
                            保存新版本
                          </Button>
                        </>
                      ) : (
                        <Button
                          icon="record"
                          disabled={!canRevise}
                          onClick={() => setEditing(true)}
                        >
                          修订方案
                        </Button>
                      )}
                    </div>
                  ) : undefined
                }
              >
                {section ? (
                  editing ? (
                    <>
                      <Field label="章节正文">
                        <textarea
                          className="chapter-editor"
                          value={contentOf(section)}
                          onChange={(e) =>
                            setSections({
                              ...sections,
                              [currentKey]: {
                                ...section,
                                content: e.target.value,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field label="不确定性与待补证据">
                        <textarea
                          rows={3}
                          value={section.uncertainty || ""}
                          onChange={(e) =>
                            setSections({
                              ...sections,
                              [currentKey]: {
                                ...section,
                                uncertainty: e.target.value,
                              },
                            })
                          }
                        />
                      </Field>
                      <Field
                        label="引用资料 ID（每行一项）"
                        hint="在循证资料卡中可查找资料 ID，保存时校验引用是否存在。"
                      >
                        <textarea
                          rows={3}
                          value={(section.citations || []).join("\n")}
                          onChange={(e) =>
                            setSections({
                              ...sections,
                              [currentKey]: {
                                ...section,
                                citations: e.target.value
                                  .split("\n")
                                  .map((v) => v.trim())
                                  .filter(Boolean),
                              },
                            })
                          }
                        />
                      </Field>
                      <p className="muted">
                        修改将保存为新方案版本；其他章节完整保留。
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="chapter-body">
                        {contentOf(section) || "此章节待补充。"}
                      </div>
                      {section.uncertainty && (
                        <div className="callout amber compact">
                          <Icon name="warning" />
                          <div>
                            <b>不确定性与待补证据</b>
                            <p>{section.uncertainty}</p>
                          </div>
                        </div>
                      )}
                      <div className="chapter-sources">
                        <h3>本章引用依据</h3>
                        {section.citations?.length ? (
                          section.citations.map((c: any, i: number) => (
                            <div key={i} className="citation-item">
                              <span>{i + 1}</span>
                              <div>
                                <Badge value="neutral">
                                  {sourceKind(resolveCitation(c))}
                                </Badge>{" "}
                                <b>{citationText(resolveCitation(c))}</b>
                                <Source item={resolveCitation(c)} />
                              </div>
                            </div>
                          ))
                        ) : (
                          <p className="muted">
                            尚未建立可核对引用，需补充原始资料。
                          </p>
                        )}
                      </div>
                    </>
                  )
                ) : (
                  <Empty title="暂无章节内容" />
                )}
                {section && currentKey === "3.6" && (
                  <MeasuresEditor
                    value={section.measures || []}
                    editing={editing}
                    onChange={(measures) =>
                      setSections({
                        ...sections,
                        [currentKey]: { ...section, measures },
                      })
                    }
                  />
                )}
                {section && currentKey === "3.9" && (
                  <BudgetEditor
                    value={section.budget_items || []}
                    editing={editing}
                    onChange={(budget_items) =>
                      setSections({
                        ...sections,
                        [currentKey]: { ...section, budget_items },
                      })
                    }
                  />
                )}
              </Panel>
            </div>
          )}
          <Panel
            title="规则检查"
            eyebrow="RULES BEFORE REVIEW"
            action={
              <div className="inline-actions">
                <Button
                  busy={busy}
                  disabled={
                    !["restorer", "expert", "admin"].includes(user.role)
                  }
                  onClick={checkPlan}
                  icon="audit"
                >
                  运行检查
                </Button>
                {editable && (
                  <Button
                    variant="primary"
                    busy={busy}
                    disabled={
                      editing ||
                      !canRevise ||
                      plan.status === "review" ||
                      plan.status === "approved"
                    }
                    onClick={() =>
                      act(async () => {
                        try {
                          await post(`/plans/${plan.id}/submit`);
                          reload();
                        } catch (e) {
                          if (e instanceof ApiError && e.details?.checks)
                            setCheck(e.details.checks);
                          throw e;
                        }
                      }, "方案已提交专家审核")
                    }
                  >
                    提交专家审核
                  </Button>
                )}
              </div>
            }
          >
            <CheckResults check={check} />
          </Panel>
          {plan.citations?.length > 0 && (
            <Panel title="本版本方案证据快照">
              <p className="muted">
                按生成当时保存的标准、病例和专家意见核对。后续病例修订不会改写此方案的来源快照；规则检查结果在上方逐条列出。
              </p>
              {plan.citations.map((citation: any, index: number) => (
                <div key={index} className="citation-item">
                  <span>{index + 1}</span>
                  <div>
                    <Badge value="neutral">
                      {sourceKind(resolveCitation(citation))}
                    </Badge>{" "}
                    <b>{citationText(resolveCitation(citation))}</b>
                    <Source item={resolveCitation(citation)} />
                    {resolveCitation(citation).text && (
                      <details>
                        <summary>查看本版本保存的依据内容</summary>
                        <p className="source-snapshot-text">
                          {resolveCitation(citation).text}
                        </p>
                      </details>
                    )}
                  </div>
                </div>
              ))}
            </Panel>
          )}
        </>
      )}
    </>
  );
}

export function ConsultationWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { user } = useApp(),
    { act, busy } = useAction();
  const plans: Entity[] = [...(record.plans || [])].sort(
    (a, b) => b.version - a.version,
  );
  const [planId, setPlanId] = useState(""),
    [comment, setComment] = useState(""),
    [decision, setDecision] = useState("approved"),
    [signature, setSignature] = useState(user.name || ""),
    [reviewComment, setReviewComment] = useState("");
  const plan =
    plans.find((p) => String(p.id) === planId) ||
    plans.find((p) => p.status === "review") ||
    plans[0];
  const canComment = ["surveyor", "restorer", "expert", "admin"].includes(
    user.role,
  );
  async function addComment(e: React.FormEvent) {
    e.preventDefault();
    await act(async () => {
      await post(`/records/${record.id}/consultations`, {
        comment,
        plan_id: plan?.id || null,
        decision: "comment",
      });
      setComment("");
      reload();
    }, "会诊意见已记录");
  }
  async function review(e: React.FormEvent) {
    e.preventDefault();
    await act(
      async () => {
        await post(`/plans/${plan.id}/review`, {
          decision,
          comment: reviewComment,
          signature,
        });
        setReviewComment("");
        reload();
      },
      decision === "approved" ? "审核意见与内部签署已记录" : "方案已退回修改",
    );
  }
  return (
    <div className="two-column">
      <div>
        <Panel title="会诊记录" eyebrow="CONSULTATION NOTES">
          {record.consultations?.length ? (
            <div className="timeline">
              {[...record.consultations].reverse().map((item: Entity) => (
                <div className="timeline-item" key={item.id}>
                  <div className="timeline-dot" />
                  <div className="timeline-meta">
                    <b>
                      {item.author_name ||
                        item.expert_name ||
                        item.user_name ||
                        item.author ||
                        item.user_id ||
                        "参与者"}
                    </b>
                    <span>{fmtTime(item.created_at || item.signed_at)}</span>
                    <Badge value={item.decision} />
                  </div>
                  <p>{item.comment}</p>
                  {item.signature && (
                    <small>内部审核署名：{item.signature}</small>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="开启一次有记录的专业讨论"
              description="会诊意见与审核记录将关联具体方案版本。"
              icon="people"
            />
          )}
          {canComment && (
            <form onSubmit={addComment} className="comment-form">
              <Field label="新增会诊意见">
                <textarea
                  required
                  rows={4}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="记录观察、待补证据、建议与适用边界。"
                />
              </Field>
              <Button variant="primary" busy={busy} type="submit">
                记录意见
              </Button>
            </form>
          )}
        </Panel>
      </div>
      <div>
        <Panel title="方案审核">
          <Field label="关联方案">
            <select
              value={plan?.id || ""}
              onChange={(e) => setPlanId(e.target.value)}
              disabled={!plans.length}
            >
              {plans.length ? (
                plans.map((p) => (
                  <option value={p.id} key={p.id}>
                    v{p.version} · {p.status}
                  </option>
                ))
              ) : (
                <option>尚无方案</option>
              )}
            </select>
          </Field>
          {plan && (
            <div className="review-metadata">
              <Badge value={plan.status} />
              <p>
                方案 v{plan.version} / 病历 v{plan.record_version}
              </p>
              <p>创建：{fmtTime(plan.created_at)}</p>
              {plan.reviewer && (
                <p>
                  审核人：
                  {typeof plan.reviewer === "object"
                    ? plan.reviewer.name
                    : plan.reviewer}
                </p>
              )}
              {plan.signed_at && <p>审核时间：{fmtTime(plan.signed_at)}</p>}
            </div>
          )}
          {user.role === "expert" ? (
            <form onSubmit={review}>
              <Field label="审核结论">
                <select
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                >
                  <option value="approved">通过审核</option>
                  <option value="rejected">退回修改</option>
                </select>
              </Field>
              <Field label="审核意见">
                <textarea
                  required
                  rows={4}
                  value={reviewComment}
                  onChange={(e) => setReviewComment(e.target.value)}
                  placeholder="请明确审核依据与必要条件。"
                />
              </Field>
              <Field
                label="审核人署名"
                hint={`须与当前账号姓名完全一致：${user.name}`}
              >
                <input
                  required
                  value={signature}
                  onChange={(e) => setSignature(e.target.value)}
                  placeholder="输入审核人姓名"
                />
              </Field>
              <div className="callout compact">
                这是绑定方案版本与内容摘要的内部审核记录，不是第三方 CA
                电子签章。
              </div>
              <Button
                variant="primary full"
                busy={busy}
                disabled={!plan || plan.status !== "review"}
                type="submit"
              >
                确认审核并记录署名
              </Button>
              {plan && plan.status !== "review" && (
                <p className="muted">当前方案尚未处于待审核状态。</p>
              )}
            </form>
          ) : (
            <div className="callout compact">
              <Icon name="people" />
              最终审核需切换为区域专家身份。作者不能审核自己的方案。
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
