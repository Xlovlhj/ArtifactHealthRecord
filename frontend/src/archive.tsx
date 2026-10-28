import { useState } from "react";
import { api, post, download, fmtTime, type Entity } from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  LoadState,
  Panel,
  Source,
  useAction,
  useApp,
  useLoad,
  Value,
} from "./ui";

export function ArchiveEntries({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { user, dict } = useApp(),
    { act, busy } = useAction();
  const [section, setSection] = useState("4.6"),
    [title, setTitle] = useState(""),
    [text, setText] = useState(""),
    [date, setDate] = useState("");
  const editable = ["surveyor", "restorer", "expert", "admin"].includes(
    user.role,
  );
  const sections: Entity[] = dict.archive_sections || [];
  const completeness: Entity[] = record.archive_completeness || [];
  async function attach(id: string, file?: File) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    await act(async () => {
      await api(`/archive-entries/${id}/file`, { method: "POST", body });
      reload();
    }, "附件已追加归档并记录文件校验值");
  }
  return (
    <>
      <Panel title="十类档案构成与缺项" eyebrow="GB/T 30235-2013 · CHAPTER 4">
        <p className="muted">
          根据实际录入的病历、检测、方案、图像和归档条目汇总。“已录入”表示存在材料，完整性和质量仍需档案审查。
        </p>
        <div className="archive-completeness">
          {sections.map((item) => {
            const status = completeness.find((row) => row.key === item.key);
            return (
              <div
                className={`archive-section-status ${status?.status || "missing"}`}
                key={item.key}
              >
                <span className="archive-section-key">{item.key}</span>
                <div>
                  <b>{item.title}</b>
                  <small>{status?.count ?? 0} 项记录</small>
                </div>
                <Badge value={status?.status === "present" ? "ready" : "warn"}>
                  {status?.status === "present" ? "已录入" : "待补充"}
                </Badge>
              </div>
            );
          })}
        </div>
        {!sections.length && <Empty title="档案标准目录尚未加载" />}
        {sections[0] && (
          <Source
            item={{
              ...sections[0],
              title: "GB/T 30235-2013 馆藏壁画保护修复档案规范",
            }}
          />
        )}
      </Panel>
      <Panel
        title="补充档案条目"
        eyebrow="PROCESS, MATERIAL TRIALS & ACCEPTANCE"
      >
        {editable ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const saved = await act(
                () =>
                  post(`/records/${record.id}/archive-entries`, {
                    expected_version: record.version,
                    section,
                    title,
                    text,
                    date,
                  }),
                "档案条目已保存，可继续追加原始附件",
              );
              if (saved) {
                setTitle("");
                setText("");
                reload();
              }
            }}
          >
            <div className="form-grid">
              <Field label="档案类别">
                <select
                  value={section}
                  onChange={(e) => setSection(e.target.value)}
                >
                  {sections.map((item) => (
                    <option value={item.key} key={item.key}>
                      {item.key} {item.title}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="档案日期">
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </Field>
              <Field label="档案条目名称" wide>
                <input
                  required
                  maxLength={300}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="如材料筛选记录、保护修复日志、验收意见"
                />
              </Field>
              <Field label="档案内容与来源" wide>
                <textarea
                  rows={4}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="写明记录内容、实施者、原始来源与结论边界。可在保存后附原始文档。"
                />
              </Field>
            </div>
            <div className="form-actions">
              <Button variant="primary" type="submit" busy={busy}>
                保存档案条目
              </Button>
            </div>
          </form>
        ) : (
          <p className="muted">
            当前身份可查阅已归集档案，由文保员、修复师或专家补充记录。
          </p>
        )}
      </Panel>
      <Panel title="已归集的补充档案">
        {record.archive_entries?.length ? (
          <div className="archive-entries">
            {[...record.archive_entries].reverse().map((entry: Entity) => (
              <article className="archive-entry" key={entry.id}>
                <div className="structured-row-heading">
                  <h3>{entry.title}</h3>
                  <Badge value="neutral">
                    {entry.section}{" "}
                    {sections.find((item) => item.key === entry.section)
                      ?.title || "档案条目"}
                  </Badge>
                </div>
                <p className="muted">
                  {entry.date || "日期未填写"} · 记录人{" "}
                  <Value value={entry.author} />
                </p>
                <p className="source-snapshot-text">
                  {entry.text || "正文未填写，请核对原始附件。"}
                </p>
                {entry.file_url ? (
                  <div className="attachment-row">
                    <Button
                      icon="download"
                      busy={busy}
                      onClick={() =>
                        act(
                          () =>
                            download(
                              entry.file_url,
                              entry.filename || "archive-attachment",
                            ),
                          "档案附件已下载",
                        )
                      }
                    >
                      {entry.filename || "下载档案附件"}
                    </Button>
                    <code>SHA-256：{entry.sha256 || "未记录"}</code>
                  </div>
                ) : editable ? (
                  <label
                    className={`button secondary upload-button ${busy ? "disabled" : ""}`}
                  >
                    追加原始附件
                    <input
                      aria-label={`附件 ${entry.title}`}
                      disabled={busy}
                      type="file"
                      accept=".pdf,.docx,.xlsx,.csv,.txt,.json,.png,.jpg,.jpeg,.tif,.tiff"
                      onChange={(e) => {
                        attach(entry.id, e.target.files?.[0]);
                        e.target.value = "";
                      }}
                    />
                  </label>
                ) : (
                  <p className="muted">未附原始文件。</p>
                )}
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="尚无补充档案条目"
            description="基本病历、影像和方案已自动计入上方目录，过程日志和验收等材料可在此补充。"
          />
        )}
      </Panel>
    </>
  );
}

export function SensitiveExport({ record }: { record: Entity }) {
  const { user } = useApp(),
    { act, busy } = useAction();
  const result = useLoad<Entity[]>(`/records/${record.id}/export-requests`);
  const [purpose, setPurpose] = useState(""),
    [comments, setComments] = useState<Entity>({});
  const sensitive = record.artifact?.sensitivity === "sensitive";
  if (!sensitive && !result.data?.length)
    return (
      <div className="callout compact">
        资料级别：内部资料。访问与导出均记录到审计；需要管理员审批时，可在结构化病历中设为“敏感资料”。
      </div>
    );
  return (
    <Panel title="敏感资料导出申请" eyebrow="VERSION-BOUND EXPORT PERMISSION">
      <div className="callout compact amber">
        资料级别：{sensitive ? "敏感资料" : "内部资料"}
        。管理员审批只授权申请人导出指定病历版本；病历发生变化后需重新申请。管理员可直接执行机构导出。
      </div>
      {sensitive && user.role !== "admin" && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const saved = await act(
              () => post(`/records/${record.id}/export-requests`, { purpose }),
              "导出申请已提交机构管理员",
            );
            if (saved) {
              setPurpose("");
              result.reload();
            }
          }}
        >
          <Field label="导出目的与使用范围">
            <textarea
              required
              rows={2}
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="说明使用者、用途、交付范围与保存要求。"
            />
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            申请导出病历 v{record.version}
          </Button>
        </form>
      )}
      <LoadState
        loading={result.loading}
        error={result.error}
        retry={result.reload}
      >
        {result.data?.length ? (
          <div className="export-requests">
            {result.data.map((item) => (
              <article className="structured-row" key={item.id}>
                <div className="structured-row-heading">
                  <b>申请 {item.id}</b>
                  <Badge value={item.status} />
                  <span className="muted">
                    病历 v{item.record_version}
                    {item.record_version !== record.version
                      ? " · 已不是当前版本"
                      : ""}
                  </span>
                </div>
                <p>{item.purpose}</p>
                <p className="muted">
                  申请人：{item.requester} · {fmtTime(item.created_at)}
                </p>
                {item.comment && <p>审批意见：{item.comment}</p>}
                {user.role === "admin" &&
                  item.status === "pending" &&
                  item.record_version === record.version && (
                    <>
                      <Field label={`审批意见 ${item.id}`}>
                        <textarea
                          rows={2}
                          value={comments[item.id] || ""}
                          onChange={(e) =>
                            setComments({
                              ...comments,
                              [item.id]: e.target.value,
                            })
                          }
                        />
                      </Field>
                      <div className="inline-actions">
                        {[
                          ["approved", "批准当前版本导出"],
                          ["rejected", "拒绝申请"],
                        ].map(([decision, label]) => (
                          <Button
                            key={decision}
                            variant={
                              decision === "approved" ? "primary" : "danger"
                            }
                            busy={busy}
                            disabled={!comments[item.id]?.trim()}
                            onClick={() =>
                              act(async () => {
                                await post(
                                  `/export-requests/${item.id}/review`,
                                  { decision, comment: comments[item.id] },
                                );
                                result.reload();
                              }, "审批结果已保存")
                            }
                          >
                            {label}
                          </Button>
                        ))}
                      </div>
                    </>
                  )}
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">暂无可查看的导出申请。</p>
        )}
      </LoadState>
    </Panel>
  );
}
