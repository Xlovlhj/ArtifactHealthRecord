import { useEffect, useRef, useState, type PointerEvent } from "react";
import {
  api,
  download,
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
  Panel,
  useAction,
  useApp,
} from "./ui";
import {
  emptyProvenance,
  ImageProvenance,
  ProvenanceFields,
  SourceBadge,
} from "./provenance";
import { AssistancePanel } from "./assistance";

type Point = [number, number];
export default function AnnotationWorkspace({
  record,
  reload,
}: {
  record: Entity;
  reload: () => void;
}) {
  const { dict, user, notify } = useApp();
  const { act, busy } = useAction();
  const editable = ["surveyor", "restorer", "admin"].includes(user.role);
  const [selectedImage, setSelectedImage] = useState<string>(
      new URLSearchParams(location.hash.split("?")[1] || "").get("image") || "",
    ),
    [items, setItems] = useState<Entity[]>([]),
    [selected, setSelected] = useState<number | null>(null),
    [mode, setMode] = useState<
      "select" | "polygon" | "centerline" | "calibrate" | "assist"
    >("select"),
    [drawing, setDrawing] = useState<Point[]>([]),
    [scalePoints, setScalePoints] = useState<Point[]>([]),
    [length, setLength] = useState(""),
    [dirty, setDirty] = useState(false),
    [draftType, setDraftType] = useState(""),
    [uploadType, setUploadType] = useState("original"),
    [uploadProvenance, setUploadProvenance] = useState<Entity>(emptyProvenance),
    [analysis, setAnalysis] = useState<Entity | null>(null),
    [jobStatus, setJobStatus] = useState(""),
    [analysisJobId, setAnalysisJobId] = useState("");
  const [assistPoints, setAssistPoints] = useState<Point[]>([]),
    [assistLabels, setAssistLabels] = useState<number[]>([]),
    [promptLabel, setPromptLabel] = useState(1);
  const svgRef = useRef<SVGSVGElement>(null),
    drag = useRef<{ item: number; point: number } | null>(null),
    fileRef = useRef<HTMLInputElement>(null);
  const images: Entity[] = record.images || [];
  const img = images.find((i) => String(i.id) === selectedImage) || images[0];
  const imageId = img?.id;
  const definitions: Entity[] = dict.diseases || [];
  const color = (type: string) =>
    definitions.find((d) => d.type === type)?.color || "#bd553e";
  useEffect(() => {
    if (!draftType && definitions.length) setDraftType(definitions[0].type);
  }, [definitions, draftType]);
  useEffect(() => {
    setItems(
      (record.diseases || [])
        .filter((item: Entity) => String(item.image_id) === String(imageId))
        .map((item: Entity) => ({
          ...item,
          polygon: item.polygon?.map((p: Point) => [...p]) || [],
          centerline: item.centerline?.map((p: Point) => [...p]) || null,
        })),
    );
    setSelected(null);
    setDrawing([]);
    setScalePoints([]);
    setDirty(false);
    setMode("select");
    setAnalysis(null);
    setAssistPoints([]);
    setAssistLabels([]);
  }, [record.version, imageId]);
  function point(e: PointerEvent): Point {
    const svg = svgRef.current!;
    const transform = svg.getScreenCTM();
    if (!transform) return [0, 0];
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const result = p.matrixTransform(transform.inverse());
    return [
      Math.round(Math.min(Math.max(result.x, 0), img.width) * 100) / 100,
      Math.round(Math.min(Math.max(result.y, 0), img.height) * 100) / 100,
    ];
  }
  function canvasDown(e: PointerEvent<SVGSVGElement>) {
    if (!editable || e.button !== 0) return;
    const p = point(e);
    if (mode === "assist") {
      if (assistPoints.length >= 100) {
        notify("每次 SAM 请求最多 100 个提示点，请清除后重新选点。", "info");
        return;
      }
      setAssistPoints((points) => [
        ...points,
        [Math.min(p[0], img.width - 1), Math.min(p[1], img.height - 1)],
      ]);
      setAssistLabels((labels) => [...labels, promptLabel]);
    } else if (mode === "centerline") {
      setDrawing((points) => [...points, p]);
    } else if (mode === "polygon") {
      setDrawing((points) => [...points, p]);
      setSelected(null);
    } else if (mode === "calibrate")
      setScalePoints((points) => (points.length < 2 ? [...points, p] : [p]));
    else if (e.target === svgRef.current || e.target instanceof SVGImageElement)
      setSelected(null);
  }
  function move(e: PointerEvent<SVGSVGElement>) {
    if (!drag.current) return;
    const { item, point: index } = drag.current,
      p = point(e);
    setItems((old) =>
      old.map((d, i) =>
        i === item
          ? {
              ...d,
              source: "manual",
              confidence: null,
              model_job_id: null,
              proposal_index: null,
              polygon: d.polygon.map((position: Point, j: number) =>
                j === index ? p : position,
              ),
            }
          : d,
      ),
    );
    setDirty(true);
  }
  function updateSelected(changes: Entity) {
    if (selected === null) return;
    setItems((old) =>
      old.map((d, i) =>
        i === selected
          ? {
              ...d,
              ...changes,
              ...(changes.type
                ? {
                    source: "manual",
                    confidence: null,
                    model_job_id: null,
                    proposal_index: null,
                    ...(changes.type !== "裂隙" ? { centerline: null } : {}),
                  }
                : {}),
            }
          : d,
      ),
    );
    setDirty(true);
  }
  function complete() {
    if (mode === "centerline") {
      if (drawing.length < 2 || selected === null) return;
      updateSelected({ centerline: drawing });
      setDrawing([]);
      setMode("select");
      return;
    }
    if (drawing.length < 3) {
      notify("多边形至少需要 3 个顶点。", "info");
      return;
    }
    const next = {
      type: draftType,
      polygon: drawing,
      severity: "待确认",
      confidence: null,
      evidence: "",
      field_evidence: "",
      confirmed: false,
      source: "manual",
    };
    setItems((old) => [...old, next]);
    setSelected(items.length);
    setDrawing([]);
    setMode("select");
    setDirty(true);
  }
  async function save() {
    await act(async () => {
      await put(`/records/${record.id}/diseases`, {
        expected_version: record.version,
        image_id: imageId,
        items: items.map((item) => ({
          type: item.type,
          polygon: item.polygon,
          centerline: item.centerline || null,
          severity: item.severity || "待确认",
          confidence: item.confidence ?? null,
          evidence: item.evidence || "",
          field_evidence: item.field_evidence || "",
          confirmed: !!item.confirmed,
          source: item.source || "manual",
          model_job_id: item.model_job_id || null,
          proposal_index: item.proposal_index ?? null,
        })),
      });
      setDirty(false);
      reload();
    }, "病害标注已保存，面积已按原图坐标重新计算。");
  }
  async function upload(file: File) {
    await act(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("image_type", uploadType);
      form.append("provenance", JSON.stringify(uploadProvenance));
      const value = await api(`/records/${record.id}/images`, {
        method: "POST",
        body: form,
      });
      setSelectedImage(String(value.id));
      reload();
      notify(
        value.duplicate
          ? value.duplicate_notice ||
              "相同原始文件已存在，未覆盖来源；请使用补录来源入口。"
          : "影像已上传并保留原始文件",
        value.duplicate ? "info" : "success",
      );
    });
    if (fileRef.current) fileRef.current.value = "";
  }
  async function analyze() {
    setAnalysis(null);
    await act(async () => {
      const value = await runJob(
        `/images/${imageId}/analyze`,
        undefined,
        (job) => {
          setJobStatus(job.status);
          setAnalysisJobId(job.id);
        },
      );
      setAnalysis(value);
      reloadQuality(value);
    }, "影像分析任务已返回");
    setJobStatus("");
  }
  function reloadQuality(value: Entity) {
    if (value.quality) img.quality = value.quality;
  }
  function addCandidates() {
    const predictions = analysis?.predictions || [];
    const valid = predictions
      .map((d: Entity, index: number) => ({
        ...d,
        proposal_index: index,
        model_job_id: analysisJobId,
      }))
      .filter((d: Entity) => Array.isArray(d.polygon) && d.polygon.length >= 3);
    setItems((old) => [
      ...old,
      ...valid.map((d: Entity) => ({
        ...d,
        severity: d.severity || "待确认",
        evidence: Array.isArray(d.evidence)
          ? d.evidence.join("；")
          : d.evidence || "",
        field_evidence: "",
        confirmed: false,
        source: "model",
      })),
    ]);
    setDirty(true);
    notify(`已载入 ${valid.length} 个待确认候选；请逐一核对后保存。`, "info");
  }
  const scale = img ? Math.max(img.width, img.height) / 750 : 1;
  const selection = selected === null ? null : items[selected];
  return (
    <div className="annotation-workspace">
      <div className="image-strip">
        <div className="image-thumbnails">
          {images.map((image) => (
            <button
              className={`image-thumb ${String(image.id) === String(imageId) ? "active" : ""}`}
              key={image.id}
              onClick={() => {
                if (
                  dirty &&
                  !window.confirm(
                    "当前影像有未保存的标注，切换将放弃这些修改。是否继续？",
                  )
                )
                  return;
                setSelectedImage(String(image.id));
              }}
            >
              <img src={imageUrl(image)} alt={image.filename} />
              <span>{image.filename}</span>
              <small>
                {image.image_type === "followup"
                  ? "复查影像"
                  : image.image_type === "document"
                    ? "资料影像"
                    : "现状影像"}
              </small>
              {image.provenance?.view_type_label && (
                <small>{image.provenance.view_type_label}</small>
              )}
              <SourceBadge image={image} demo={record.is_demo} />
            </button>
          ))}
        </div>
        {editable && (
          <div className="upload-controls">
            <select
              value={uploadType}
              onChange={(e) => setUploadType(e.target.value)}
              aria-label="上传影像类型"
            >
              <option value="original">原始现状影像</option>
              <option value="followup">复查影像</option>
              <option value="document">资料影像</option>
            </select>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/tiff"
              ref={fileRef}
              hidden
              onChange={(e) => {
                if (e.target.files?.[0]) upload(e.target.files[0]);
              }}
            />
            <Button
              icon="plus"
              busy={busy}
              onClick={() => fileRef.current?.click()}
            >
              上传影像
            </Button>
          </div>
        )}
      </div>
      {editable && (
        <details className="upload-provenance">
          <summary>上传前填写影像来源、授权与采集信息</summary>
          <p className="muted">
            这里的填写内容随下一张上传影像一起保存。未填写时按「来源未核实」入库，不计入已核实真实数据。
          </p>
          <ProvenanceFields
            value={uploadProvenance}
            onChange={setUploadProvenance}
          />
        </details>
      )}
      {!img ? (
        <Panel>
          <Empty
            title="从一张现场照片开始"
            description="上传原始现状影像后，可以开展质量检查、尺度标定和病害标注。"
            icon="image"
          />
        </Panel>
      ) : (
        <>
          <ImageProvenance
            image={img}
            record={record}
            reload={reload}
            hasUnsavedAnnotations={dirty}
          />
          <div className="annotation-layout">
            <Panel className="canvas-panel">
              <div className="canvas-toolbar">
                <div className="button-group">
                  <button
                    disabled={!editable}
                    title="选择标注并拖动顶点"
                    className={mode === "select" ? "active" : ""}
                    onClick={() => {
                      setMode("select");
                      setDrawing([]);
                    }}
                  >
                    <Icon name="polygon" size={16} />
                    选择
                  </button>
                  <button
                    disabled={!editable}
                    className={mode === "polygon" ? "active" : ""}
                    onClick={() => {
                      setMode("polygon");
                      setScalePoints([]);
                      setSelected(null);
                    }}
                  >
                    <Icon name="plus" size={16} />
                    多边形
                  </button>
                  <button
                    disabled={!editable}
                    className={mode === "calibrate" ? "active" : ""}
                    onClick={() => {
                      setMode("calibrate");
                      setDrawing([]);
                      setSelected(null);
                    }}
                  >
                    <Icon name="ruler" size={16} />
                    标尺
                  </button>
                </div>
                <span className="canvas-dimensions">
                  {img.width} × {img.height} px
                </span>
                {dirty && <Badge value="warn">有未保存修改</Badge>}
              </div>
              {mode === "polygon" && (
                <div className="drawing-toolbar">
                  <select
                    value={draftType}
                    onChange={(e) => setDraftType(e.target.value)}
                    aria-label="新标注病害类型"
                  >
                    {definitions.map((d) => (
                      <option key={d.type} value={d.type}>
                        {d.type}
                      </option>
                    ))}
                  </select>
                  <span>依次点击边界：{drawing.length} 个顶点</span>
                  <Button
                    onClick={() => setDrawing((points) => points.slice(0, -1))}
                    disabled={!drawing.length}
                    icon="undo"
                  >
                    撤销点
                  </Button>
                  <Button
                    variant="primary"
                    onClick={complete}
                    disabled={drawing.length < 3}
                    icon="check"
                  >
                    闭合区域
                  </Button>
                </div>
              )}
              {mode === "centerline" && (
                <div className="drawing-toolbar">
                  <span>沿当前裂隙主线依次点击：{drawing.length} 个点</span>
                  <Button
                    onClick={() => setDrawing((points) => points.slice(0, -1))}
                    disabled={!drawing.length}
                    icon="undo"
                  >
                    撤销点
                  </Button>
                  <Button
                    variant="primary"
                    onClick={complete}
                    disabled={drawing.length < 2}
                    icon="check"
                  >
                    完成中心线
                  </Button>
                  <Button
                    onClick={() => {
                      setDrawing([]);
                      setMode("select");
                    }}
                  >
                    取消绘制
                  </Button>
                </div>
              )}
              {mode === "calibrate" && (
                <div className="drawing-toolbar">
                  <span>
                    在原图点击标尺的两个端点（{scalePoints.length}/2）
                  </span>
                  <input
                    type="number"
                    min="0.001"
                    step="any"
                    placeholder="实际长度 cm"
                    aria-label="两点之间实际长度厘米"
                    value={length}
                    onChange={(e) => setLength(e.target.value)}
                  />
                  <Button
                    variant="primary"
                    busy={busy}
                    disabled={scalePoints.length !== 2 || Number(length) <= 0}
                    onClick={() =>
                      act(async () => {
                        await put(`/images/${imageId}/calibration`, {
                          points: scalePoints,
                          length_cm: Number(length),
                        });
                        setMode("select");
                        reload();
                      }, "尺度标定已保存")
                    }
                  >
                    保存标定
                  </Button>
                </div>
              )}
              <div
                className={`image-canvas ${mode !== "select" ? "crosshair" : ""}`}
              >
                <svg
                  ref={svgRef}
                  viewBox={`0 0 ${img.width} ${img.height}`}
                  role="img"
                  aria-label="原图病害多边形标注画布"
                  onPointerDown={canvasDown}
                  onPointerMove={move}
                  onPointerUp={() => {
                    drag.current = null;
                  }}
                  onPointerCancel={() => {
                    drag.current = null;
                  }}
                  style={{
                    aspectRatio: `${img.width}/${img.height}`,
                    touchAction: "none",
                  }}
                >
                  <image
                    href={imageUrl(img)}
                    width={img.width}
                    height={img.height}
                  />
                  {assistPoints.map((p, index) => (
                    <g key={`prompt-${index}`} pointerEvents="none">
                      <circle
                        cx={p[0]}
                        cy={p[1]}
                        r={6 * scale}
                        fill={assistLabels[index] ? "#168c5a" : "#c44035"}
                        stroke="white"
                        strokeWidth={1.5 * scale}
                      />
                      <text
                        x={p[0]}
                        y={p[1] + 3 * scale}
                        textAnchor="middle"
                        fill="white"
                        fontSize={10 * scale}
                      >
                        {assistLabels[index] ? "+" : "−"}
                      </text>
                    </g>
                  ))}
                  {items.map((item, index) => (
                    <g key={index}>
                      <polygon
                        points={(item.polygon || [])
                          .map((p: Point) => p.join(","))
                          .join(" ")}
                        fill={color(item.type)}
                        fillOpacity={selected === index ? 0.32 : 0.18}
                        stroke={color(item.type)}
                        strokeWidth={(selected === index ? 3 : 1.8) * scale}
                        strokeDasharray={
                          item.confirmed
                            ? undefined
                            : `${5 * scale} ${3 * scale}`
                        }
                        onPointerDown={(e) => {
                          if (mode === "select") {
                            e.stopPropagation();
                            setSelected(index);
                          }
                        }}
                      />
                      {item.centerline?.length >= 2 && (
                        <polyline
                          points={item.centerline
                            .map((p: Point) => p.join(","))
                            .join(" ")}
                          fill="none"
                          stroke={color(item.type)}
                          strokeWidth={2.5 * scale}
                          pointerEvents="none"
                        />
                      )}
                      {item.polygon?.length > 0 && (
                        <g
                          transform={`translate(${item.polygon[0][0]},${Math.max(20 * scale, item.polygon[0][1])})`}
                          pointerEvents="none"
                        >
                          <rect
                            y={-19 * scale}
                            width={(item.type.length * 13 + 33) * scale}
                            height={20 * scale}
                            rx={3 * scale}
                            fill={color(item.type)}
                          />
                          <text
                            x={5 * scale}
                            y={-5 * scale}
                            fill="#fff"
                            fontSize={12 * scale}
                          >
                            {index + 1} {item.type}
                          </text>
                        </g>
                      )}
                      {selected === index &&
                        mode === "select" &&
                        editable &&
                        (item.polygon || []).map((p: Point, j: number) => (
                          <circle
                            key={j}
                            cx={p[0]}
                            cy={p[1]}
                            r={5 * scale}
                            stroke={color(item.type)}
                            strokeWidth={2 * scale}
                            fill="white"
                            className="vertex"
                            onPointerDown={(e) => {
                              e.stopPropagation();
                              drag.current = { item: index, point: j };
                              svgRef.current?.setPointerCapture(e.pointerId);
                            }}
                          />
                        ))}
                    </g>
                  ))}
                  {drawing.length > 0 && (
                    <g>
                      <polyline
                        points={drawing.map((p) => p.join(",")).join(" ")}
                        fill={mode === "centerline" ? "none" : color(draftType)}
                        fillOpacity="0.15"
                        stroke={color(draftType)}
                        strokeWidth={2 * scale}
                      />
                      {drawing.map((p, i) => (
                        <circle
                          key={i}
                          cx={p[0]}
                          cy={p[1]}
                          r={4 * scale}
                          fill={color(draftType)}
                        />
                      ))}
                    </g>
                  )}
                  {(mode === "calibrate"
                    ? scalePoints
                    : img.calibration?.points || []
                  ).length > 0 && (
                    <g pointerEvents="none">
                      <polyline
                        points={(mode === "calibrate"
                          ? scalePoints
                          : img.calibration.points
                        )
                          .map((p: Point) => p.join(","))
                          .join(" ")}
                        fill="none"
                        stroke="#12bbd2"
                        strokeWidth={3 * scale}
                      />
                      {(mode === "calibrate"
                        ? scalePoints
                        : img.calibration.points
                      ).map((p: Point, i: number) => (
                        <circle
                          key={i}
                          cx={p[0]}
                          cy={p[1]}
                          r={5 * scale}
                          fill="#12bbd2"
                          stroke="white"
                          strokeWidth={1.5 * scale}
                        />
                      ))}
                    </g>
                  )}
                </svg>
              </div>
              <div className="canvas-caption">
                <span>
                  <i className="legend-line" />
                  实线：人工已确认 <i className="legend-line dashed" />
                  虚线：待确认
                </span>
                <span>原图坐标 · 点击区域选择 · 拖动顶点修正</span>
              </div>
              <div className="canvas-bottom">
                <div>
                  <b>{img.filename}</b>
                  <p>
                    {img.calibration
                      ? `已标定：${img.calibration.length_cm} cm / 两点距离`
                      : "未做尺度标定：当前仅可计算像素面积与面积比例"}
                  </p>
                </div>
                {editable && (
                  <Button
                    variant="primary"
                    busy={busy}
                    onClick={save}
                    disabled={!dirty}
                    icon="check"
                  >
                    保存标注
                  </Button>
                )}
              </div>
            </Panel>
            <div className="annotation-aside">
              {editable && (
                <AssistancePanel
                  key={`${img.id}:${record.version}`}
                  image={img}
                  record={record}
                  active={mode === "assist"}
                  toggle={() => {
                    setMode(mode === "assist" ? "select" : "assist");
                    setDrawing([]);
                    setScalePoints([]);
                  }}
                  points={assistPoints}
                  labels={assistLabels}
                  promptLabel={promptLabel}
                  setPromptLabel={setPromptLabel}
                  clear={() => {
                    setAssistPoints([]);
                    setAssistLabels([]);
                  }}
                  adopt={(candidate) => {
                    setItems((items) => [...items, candidate]);
                    setSelected(items.length);
                    setDirty(true);
                    setMode("select");
                  }}
                />
              )}
              <Panel
                title="病害区域"
                action={<span className="count-pill">{items.length}</span>}
              >
                <div className="disease-list">
                  {items.length ? (
                    items.map((d, index) => (
                      <button
                        key={index}
                        className={`disease-row ${selected === index ? "active" : ""}`}
                        onClick={() => {
                          setSelected(index);
                          setMode("select");
                        }}
                      >
                        <i style={{ background: color(d.type) }} />
                        <div>
                          <b>
                            {String(index + 1).padStart(2, "0")} · {d.type}
                          </b>
                          <small>
                            {d.confirmed ? "人工已确认" : "待核对"} ·{" "}
                            {d.source === "model" ? "模型候选" : "人工标注"}
                          </small>
                        </div>
                        <span>{d.severity || "待确认"}</span>
                      </button>
                    ))
                  ) : (
                    <p className="muted small-padding">
                      点击「多边形」，沿病害边界逐点绘制。
                    </p>
                  )}
                </div>
              </Panel>
              {selection && (
                <Panel title="标注属性" className="annotation-properties">
                  <Field label="病害类别">
                    <select
                      disabled={!editable}
                      value={selection.type}
                      onChange={(e) => updateSelected({ type: e.target.value })}
                    >
                      {definitions.map((d) => (
                        <option key={d.type} value={d.type}>
                          {d.type}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {selection.type === "裂隙" && (
                    <div className="callout compact">
                      <div>
                        <b>裂隙中心线</b>
                        <p>
                          面积多边形记录受损区域；标准线型需沿实际裂隙另绘中心线，不能把闭合区域边界当作裂隙走向。
                        </p>
                        <p>
                          {selection.centerline?.length >= 2
                            ? `已绘制 ${selection.centerline.length} 个中心线点`
                            : "尚未绘制，导出时会标记待补"}
                        </p>
                        {editable && (
                          <div className="inline-actions">
                            <Button
                              onClick={() => {
                                setMode("centerline");
                                setDrawing([]);
                                setScalePoints([]);
                              }}
                            >
                              绘制裂隙中心线
                            </Button>
                            {selection.centerline?.length >= 2 && (
                              <Button
                                onClick={() =>
                                  updateSelected({ centerline: null })
                                }
                              >
                                清除中心线
                              </Button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  <Field label="严重程度">
                    <select
                      disabled={!editable}
                      value={selection.severity || "待确认"}
                      onChange={(e) =>
                        updateSelected({ severity: e.target.value })
                      }
                    >
                      {["待确认", "轻度", "中度", "重度"].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="影像观察依据">
                    <textarea
                      disabled={!editable}
                      rows={3}
                      value={selection.evidence || ""}
                      onChange={(e) =>
                        updateSelected({ evidence: e.target.value })
                      }
                      placeholder="描述纹理、色泽、裂隙或翘起等可观察现象。"
                    />
                  </Field>
                  <Field
                    label="现场核验证据"
                    hint={
                      definitions.find((d) => d.type === selection.type)
                        ?.requires_field_evidence
                        ? "此类病害需要现场检测或专业核实，影像不足以确认。"
                        : undefined
                    }
                  >
                    <textarea
                      disabled={!editable}
                      rows={2}
                      value={selection.field_evidence || ""}
                      onChange={(e) =>
                        updateSelected({ field_evidence: e.target.value })
                      }
                      placeholder="记录检测方法、实测结果及来源。"
                    />
                  </Field>
                  <label className="check-field">
                    <input
                      type="checkbox"
                      disabled={!editable}
                      checked={!!selection.confirmed}
                      onChange={(e) =>
                        updateSelected({ confirmed: e.target.checked })
                      }
                    />
                    已人工核对并确认
                  </label>
                  <div className="callout compact">
                    <div>
                      <b>病害名称依据</b>
                      <p>
                        {definitions.find((d) => d.type === selection.type)
                          ?.standard_code || "尚未关联标准"}
                      </p>
                      <Badge
                        value={
                          definitions.find((d) => d.type === selection.type)
                            ?.symbol_verified
                            ? "ready"
                            : "warn"
                        }
                      >
                        {definitions.find((d) => d.type === selection.type)
                          ?.symbol_verified
                          ? "标准图示参数已核对"
                          : "标准图示待核 · 当前为工作标记"}
                      </Badge>
                    </div>
                  </div>
                  <div className="measurement-grid">
                    <div>
                      <span>像素面积</span>
                      <b>
                        {dirty ? "保存后计算" : fmtNum(selection.area_px)}
                        <small> px²</small>
                      </b>
                    </div>
                    <div>
                      <span>实测面积</span>
                      <b>
                        {dirty ? "保存后计算" : fmtNum(selection.area_cm2)}
                        {selection.area_cm2 != null && <small> cm²</small>}
                      </b>
                    </div>
                    <div>
                      <span>影像面积比例</span>
                      <b>
                        {dirty
                          ? "保存后计算"
                          : selection.area_ratio == null
                            ? "未计算"
                            : `${fmtNum(selection.area_ratio * 100)}%`}
                      </b>
                    </div>
                    <div>
                      <span>模型置信度</span>
                      <b>
                        {selection.confidence == null
                          ? "人工标注 / 无评分"
                          : fmtNum(selection.confidence)}
                      </b>
                    </div>
                  </div>
                  {editable && (
                    <Button
                      variant="danger full"
                      icon="trash"
                      onClick={() => {
                        setItems((old) => old.filter((_, i) => i !== selected));
                        setSelected(null);
                        setDirty(true);
                      }}
                    >
                      删除此区域
                    </Button>
                  )}
                </Panel>
              )}
              <Panel title="影像分析" action={<Icon name="spark" size={18} />}>
                <p className="muted">
                  执行质量检查并读取分割模型状态。模型候选需人工核对后才写入病历。
                </p>
                <Button
                  variant="secondary full"
                  busy={busy && !!jobStatus}
                  disabled={
                    busy ||
                    !["surveyor", "restorer", "expert", "admin"].includes(
                      user.role,
                    )
                  }
                  onClick={analyze}
                >
                  质量检查 / 分割候选
                </Button>
                {jobStatus && <p className="muted">任务状态：{jobStatus}</p>}
                {analysis && (
                  <div className="analysis-result">
                    <Badge
                      value={
                        analysis.status ||
                        analysis.segmentation?.status ||
                        "completed"
                      }
                    />
                    <p>
                      {analysis.message ||
                        analysis.reason ||
                        analysis.segmentation?.reason ||
                        analysis.limitations}
                    </p>
                    {analysis.predictions?.length > 0 && (
                      <Button onClick={addCandidates}>
                        载入 {analysis.predictions.length} 个候选
                      </Button>
                    )}
                    <details>
                      <summary>查看任务结果与模型版本</summary>
                      <pre>{JSON.stringify(analysis, null, 2)}</pre>
                    </details>
                  </div>
                )}
                {img.quality && (
                  <div className="quality-details">
                    <h3>影像质量记录</h3>
                    <div className="measurement-grid">
                      <div>
                        <span>边缘清晰度统计</span>
                        <b>
                          {fmtNum(img.quality.sharpness_laplacian_variance)}
                        </b>
                      </div>
                      <div>
                        <span>暗部比例</span>
                        <b>
                          {img.quality.underexposed_fraction == null
                            ? "未计算"
                            : `${fmtNum(img.quality.underexposed_fraction * 100)}%`}
                        </b>
                      </div>
                      <div>
                        <span>亮部比例</span>
                        <b>
                          {img.quality.overexposed_fraction == null
                            ? "未计算"
                            : `${fmtNum(img.quality.overexposed_fraction * 100)}%`}
                        </b>
                      </div>
                    </div>
                    {(img.quality.warnings || []).map(
                      (warning: string, i: number) => (
                        <p className="quality-warning" key={i}>
                          {warning}
                        </p>
                      ),
                    )}
                    <p className="muted">{img.quality.threshold_basis}</p>
                    <details>
                      <summary>查看质量计算与阈值记录</summary>
                      <pre>{JSON.stringify(img.quality, null, 2)}</pre>
                    </details>
                  </div>
                )}
              </Panel>
            </div>
          </div>
          <Panel
            title="病害图与尺度记录"
            action={
              <div className="inline-actions">
                <Button
                  icon="download"
                  busy={busy}
                  onClick={() =>
                    act(
                      () =>
                        download(
                          `/records/${record.id}/disease-map.svg?image_id=${imageId}`,
                          `${record.id}-disease-map.svg`,
                        ),
                      "SVG 病害图已导出",
                    )
                  }
                >
                  SVG
                </Button>
                <Button
                  icon="download"
                  busy={busy}
                  onClick={() =>
                    act(
                      () =>
                        download(
                          `/records/${record.id}/disease-map.pdf?image_id=${imageId}`,
                          `${record.id}-disease-map.pdf`,
                        ),
                      "PDF 病害图已导出",
                    )
                  }
                >
                  PDF
                </Button>
              </div>
            }
          >
            <div className="inline-actions">
              <p className="muted">
                病害图使用已保存标注，保留未确认标识、图例与比例信息。当前
                {img.calibration
                  ? "已完成两点尺度标定"
                  : "尚未标定，不输出推测的物理面积"}
                。
              </p>
              {img.calibration && editable && (
                <Button
                  variant="danger"
                  busy={busy}
                  onClick={() =>
                    act(async () => {
                      await post(`/images/${imageId}/calibration/clear`);
                      reload();
                    }, "尺度标定已清除")
                  }
                >
                  清除标定
                </Button>
              )}
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
