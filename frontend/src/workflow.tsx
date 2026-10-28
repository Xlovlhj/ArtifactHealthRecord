import { type Entity } from "./api";
import { Badge } from "./ui";

export function RecordWorkflow({
  record,
  onNavigate,
}: {
  record: Entity;
  onNavigate: (tab: string) => void;
}) {
  const images: Entity[] = record.images || [],
    diseases: Entity[] = record.diseases || [];
  const plan = (record.plans || []).find(
    (p: Entity) => p.record_version === record.version,
  );
  const sourced = images.filter(
    (i) => i.provenance?.review_status === "verified",
  ).length;
  const confirmed = diseases.filter((d) => d.confirmed).length;
  const sections: Entity[] = record.archive_completeness || [];
  const present = sections.filter((s) => s.status === "present").length;
  const steps = [
    {
      tab: "images",
      title: "采集、来源与质量检查",
      state: images.length ? "pending" : "draft",
      text: `${images.length} 张影像，${sourced} 张已复核来源；现场拍摄还应记录色卡、比例尺、设备与光照。`,
    },
    {
      tab: "images",
      title: "分割候选与人工病害图",
      state:
        diseases.length && confirmed === diseases.length ? "ready" : "pending",
      text: `${confirmed} / ${diseases.length} 处已人工确认；${images.filter((i) => i.calibration).length} 张影像有尺度标定。标准符号核验另见图示说明。`,
    },
    {
      tab: "record",
      title: "结构化病历与待核查假设",
      state:
        record.chief_complaint && record.diagnosis?.hypothesis
          ? "ready"
          : "pending",
      text: record.diagnosis?.hypothesis
        ? "已记录诊断假设；继续核对检查报告、病因证据和不确定性。"
        : "填写现场主诉、保护历史、检查记录、诊断假设与不确定性。",
    },
    {
      tab: "evidence",
      title: "相似病例与规范依据",
      state: record.evidence_ids?.length ? "ready" : "pending",
      text: `已选择 ${record.evidence_ids?.length || 0} 条依据；查看原文、既往处置和成败结果后再用于方案。`,
    },
    {
      tab: "plans",
      title: "13 节方案与规则检查",
      state:
        plan?.checks?.overall === "pass"
          ? "ready"
          : plan?.checks?.overall === "block"
            ? "block"
            : "pending",
      text: plan
        ? `当前病历关联方案 v${plan.version}；${Object.keys(plan.sections || {}).length} 个章节，${plan.checks ? "已运行规则检查，请核对逐条结果" : "待运行规则检查"}。`
        : "当前病历版本尚无方案，生成或更新后逐章补齐内容、引用、工序及预算。",
    },
    {
      tab: "consultation",
      title: "会诊批注与专家署名",
      state: plan?.status === "approved" ? "ready" : "pending",
      text:
        plan?.status === "approved"
          ? "当前版本已有专家审核记录；修改病历或方案后需重新审核。"
          : "通过阻断检查后提交，专家使用自己的账号审阅并记录意见与署名。",
    },
    {
      tab: "simulation",
      title: "术前模拟与复查影像对比",
      state: record.simulations?.length ? "ready" : "pending",
      text: `${record.simulations?.length || 0} 份独立水印模拟。复查影像需配准与人工核验，模拟不进入正式修复事实。`,
    },
    {
      tab: "archive",
      title: "过程记录与档案归集",
      state:
        sections.length > 0 && present === sections.length
          ? "ready"
          : "pending",
      text: `${present} / ${sections.length || 10} 类档案已有内容；逐项核查调查、施工、验收与附件，填入不等于专业验收。`,
    },
  ];
  return (
    <details className="record-workflow">
      <summary>查看本病历的完整保护流程与待办</summary>
      <p className="muted">
        以下状态来自当前版本的实际记录，用于找到下一步工作入口；不替代专家对资料质量和工程合规性的判断。
      </p>
      <ol>
        {steps.map((step, i) => (
          <li key={i}>
            <span className="workflow-number">{i + 1}</span>
            <div>
              <b>{step.title}</b>
              <p>{step.text}</p>
            </div>
            <Badge value={step.state}>
              {step.state === "ready"
                ? "已有记录"
                : step.state === "block"
                  ? "存在阻断"
                  : "待完善"}
            </Badge>
            <button
              className="text-button"
              onClick={() => onNavigate(step.tab)}
            >
              进入处理 →
            </button>
          </li>
        ))}
      </ol>
    </details>
  );
}
