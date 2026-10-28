import { useEffect, useRef, useState } from "react";
import { fmtNum, imageUrl, runJob, type Entity } from "./api";
import { Badge, Button, Field, Panel, useAction, useApp } from "./ui";

export function AssistancePanel({
  image,
  record,
  active,
  toggle,
  points,
  labels,
  promptLabel,
  setPromptLabel,
  clear,
  adopt,
}: {
  image: Entity;
  record: Entity;
  active: boolean;
  toggle: () => void;
  points: number[][];
  labels: number[];
  promptLabel: number;
  setPromptLabel: (label: number) => void;
  clear: () => void;
  adopt: (candidate: Entity) => void;
}) {
  const { dict, notify } = useApp(),
    { act, busy } = useAction();
  const requestGeneration = useRef(0);
  const sourceScope = useRef({
    imageId: String(image.id),
    version: record.version,
  });
  sourceScope.current = { imageId: String(image.id), version: record.version };
  const [result, setResult] = useState<Entity | null>(null),
    [selected, setSelected] = useState(0),
    [type, setType] = useState(""),
    [status, setStatus] = useState(""),
    [adopted, setAdopted] = useState<number[]>([]);
  useEffect(() => {
    requestGeneration.current += 1;
    setResult(null);
    setType("");
    setAdopted([]);
    setStatus("");
    return () => {
      requestGeneration.current += 1;
    };
  }, [image.id, record.version]);
  const currentResult =
    result &&
    String(result.image_id) === String(image.id) &&
    result.source_record_version === record.version;
  const candidate = currentResult ? result.predictions?.[selected] : null;
  const complex =
    candidate &&
    ((candidate.holes || []).length > 0 ||
      (candidate.polygons || [candidate.polygon]).length !== 1);
  async function run() {
    const generation = ++requestGeneration.current;
    const requestScope = { ...sourceScope.current };
    const isCurrentRequest = () =>
      generation === requestGeneration.current &&
      requestScope.imageId === sourceScope.current.imageId &&
      requestScope.version === sourceScope.current.version;
    setResult(null);
    setAdopted([]);
    const value = await act(() =>
      runJob(
        `/images/${image.id}/assist`,
        { expected_version: record.version, points, point_labels: labels },
        (job) => {
          if (isCurrentRequest()) setStatus(job.status);
        },
      ),
    );
    if (!isCurrentRequest()) return;
    setStatus("");
    if (value) {
      if (
        String(value.image_id) !== requestScope.imageId ||
        value.source_record_version !== requestScope.version
      ) {
        notify(
          "SAM 结果不属于当前影像或病历版本，已忽略；请重新提交辅助标注。",
          "error",
        );
        return;
      }
      setResult(value);
      setSelected(0);
    }
  }
  return (
    <Panel title="SAM 交互辅助标注" eyebrow="PROMPTED REGION PROPOSALS">
      <p className="muted">
        先点选需要的区域，再补充背景点排除相邻区域。SAM
        只提出边界，病害类别由你选择。
      </p>
      <div className="inline-actions">
        <Button variant={active ? "primary" : ""} onClick={toggle}>
          {active ? "结束点选" : "开始 SAM 点选"}
        </Button>
        <Button onClick={clear} disabled={!points.length}>
          清除提示点
        </Button>
      </div>
      {active && (
        <Field label="SAM 提示点类型">
          <select
            value={promptLabel}
            onChange={(e) => setPromptLabel(Number(e.target.value))}
          >
            <option value={1}>前景点 · 保留区域（绿色）</option>
            <option value={0}>背景点 · 排除区域（红色）</option>
          </select>
        </Field>
      )}
      <p className="muted">
        已选 {labels.filter((x) => x === 1).length} 个前景点、
        {labels.filter((x) => x === 0).length} 个背景点。
      </p>
      <Button
        variant="secondary full"
        busy={busy}
        disabled={!points.length}
        onClick={run}
      >
        生成 SAM 区域候选
      </Button>
      {status && (
        <p role="status">辅助任务：{status}。真实模型推理可能需要较长时间。</p>
      )}
      {result && currentResult && (
        <div className="sam-result">
          <Badge value={result.status === "ok" ? "ready" : "warn"}>
            {result.predictions?.length
              ? `${result.predictions.length} 个区域候选 · 待人工判断`
              : "当前未得到可用候选"}
          </Badge>
          {result.reason && <p>{result.reason}</p>}
          {(result.limitations || []).map((item: string, index: number) => (
            <p className="muted" key={index}>
              {item}
            </p>
          ))}
          {candidate && (
            <>
              <Field label="SAM 候选区域">
                <select
                  value={selected}
                  onChange={(e) => {
                    setSelected(Number(e.target.value));
                    setType("");
                  }}
                >
                  {result.predictions.map((item: Entity, index: number) => (
                    <option key={index} value={index}>
                      候选 {index + 1} · 内部 IoU 评分{" "}
                      {fmtNum(item.confidence, 3)}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="sam-mask-preview">
                <figure>
                  <img src={imageUrl(image)} alt="SAM 原始影像参考" />
                  <figcaption>原图</figcaption>
                </figure>
                <figure>
                  <img
                    src={candidate.mask_data_url}
                    alt={`SAM 候选 ${selected + 1} 完整二值掩膜`}
                  />
                  <figcaption>白色为候选区域（含全部分区与孔洞）</figcaption>
                </figure>
              </div>
              <p>
                候选掩膜：{candidate.area_pixels} 像素；
                {(candidate.polygons || [candidate.polygon]).length} 个外轮廓、
                {(candidate.holes || []).length} 个孔洞。
              </p>
              {complex && (
                <div className="callout amber compact">
                  此候选含多个区域或孔洞，不能直接转换成单一多边形。请保留完整掩膜作为参考，使用人工多边形逐区描绘，避开孔洞；系统不会静默丢弃这些结构。
                </div>
              )}
              <Field label="人工选择候选病害类别">
                <select value={type} onChange={(e) => setType(e.target.value)}>
                  <option value="">请根据证据选择病害类别</option>
                  {(dict.diseases || []).map((item: Entity) => (
                    <option key={item.type} value={item.type}>
                      {item.type}
                    </option>
                  ))}
                </select>
              </Field>
              <Button
                variant="primary full"
                disabled={complex || !type || adopted.includes(selected)}
                onClick={() => {
                  if (
                    String(result.image_id) !== sourceScope.current.imageId ||
                    result.source_record_version !== sourceScope.current.version
                  ) {
                    notify(
                      "影像或病历版本已变化，请重新生成 SAM 候选后再采用。",
                      "error",
                    );
                    return;
                  }
                  adopt({
                    type,
                    polygon: candidate.polygon,
                    severity: "待确认",
                    confirmed: false,
                    source: "manual",
                    confidence: null,
                    field_evidence: "",
                    evidence: `由人工选择类别并采用 SAM 提示边界；任务 ${result.task_id || "见审计任务"}；模型 ${result.model_version || "未记录"}；候选 ${selected + 1}，内部 IoU 预测分数 ${candidate.confidence}（未经校准，不是病害分类置信度）。提示点 ${JSON.stringify(result.prompts || { points, point_labels: labels })}。`,
                  });
                  setAdopted((items) => [...items, selected]);
                }}
              >
                {adopted.includes(selected)
                  ? "已载入人工草稿"
                  : "采用为人工标注草稿"}
              </Button>
              <p className="muted">
                载入后仍须修正边界、填写证据并保存；不会自动确认病害。
              </p>
            </>
          )}
          <details>
            <summary>任务来源与模型版本</summary>
            <p>任务：{result.task_id || "未记录"}</p>
            <p className="file-checksum">
              模型：{result.model_version || "未配置"}
            </p>
            <p>来源病历版本：{result.source_record_version ?? "未记录"}</p>
          </details>
        </div>
      )}
    </Panel>
  );
}
