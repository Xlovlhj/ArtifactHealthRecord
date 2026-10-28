import type { Entity } from "./api";
import { MaterialTests } from "./material-tests";
import { Button, Field, useApp } from "./ui";

type Column = { key: string; label: string; type?: string; wide?: boolean };
const clinicalSections: {
  key: string;
  title: string;
  description: string;
  columns: Column[];
}[] = [
  {
    key: "previous_treatments",
    title: "既往处置",
    description: "记录已有干预及其结果，保留实施者与原始资料出处。",
    columns: [
      { key: "date", label: "处置日期", type: "date" },
      { key: "operator", label: "实施者" },
      { key: "method", label: "处置方法", wide: true },
      { key: "materials", label: "使用材料" },
      { key: "outcome", label: "已有结果或问题" },
      { key: "source", label: "记录出处", wide: true },
    ],
  },
  {
    key: "examinations",
    title: "检查与检测",
    description:
      "观察事实与检测结果分开记录；无法测定的内容留空，不填推测数值。",
    columns: [
      { key: "date", label: "检查日期", type: "date" },
      { key: "method", label: "方法 / 仪器" },
      { key: "location", label: "检查位置" },
      { key: "result", label: "结果 / 实测值" },
      { key: "unit", label: "单位" },
      { key: "source", label: "报告 / 来源" },
      { key: "uncertainty", label: "局限与待核实事项", wide: true },
    ],
  },
  {
    key: "differential_diagnoses",
    title: "鉴别诊断与待核查假设",
    description: "并列记录不同解释，说明支持与反对的证据，以及还缺少什么检查。",
    columns: [
      { key: "hypothesis", label: "候选解释", wide: true },
      { key: "supporting_evidence", label: "支持证据", wide: true },
      { key: "opposing_evidence", label: "反对证据 / 不一致之处", wide: true },
      { key: "needed_checks", label: "需要补充的检查", wide: true },
    ],
  },
  {
    key: "followups",
    title: "随访与复查",
    description:
      "连续记录变化、处置和下一次复查时间，不把一次照片差异直接当作病害变化。",
    columns: [
      { key: "date", label: "复查日期", type: "date" },
      { key: "observer", label: "观察记录人" },
      { key: "findings", label: "观察到的变化", wide: true },
      { key: "action", label: "后续行动", wide: true },
      { key: "next_date", label: "下次复查日期", type: "date" },
    ],
  },
];
export const riskLabels: Record<string, string> = {
  unassessed: "尚未评估",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  urgent: "需紧急专业评估",
};
export function ClinicalDataEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: Entity;
  onChange: (value: Entity) => void;
  disabled?: boolean;
}) {
  const { user } = useApp();
  function updateRow(key: string, index: number, field: string, text: string) {
    onChange({
      ...value,
      [key]: (value[key] || []).map((row: Entity, i: number) =>
        i === index ? { ...row, [field]: text } : row,
      ),
    });
  }
  return (
    <div className="clinical-data-editor">
      <div className="form-section-label">03 / 既往处置、检查、鉴别与随访</div>
      {clinicalSections.map((section) => (
        <details
          className="structured-section"
          key={section.key}
          open={(value[section.key] || []).length > 0}
        >
          <summary>
            {section.title}
            <span className="count-pill">
              {(value[section.key] || []).length}
            </span>
          </summary>
          <p className="muted">{section.description}</p>
          {(value[section.key] || []).map((row: Entity, index: number) => (
            <div className="structured-row" key={index}>
              <div className="structured-row-heading">
                <b>
                  {section.title} · {index + 1}
                </b>
                {!disabled && (
                  <Button
                    type="button"
                    variant="danger"
                    icon="trash"
                    onClick={() =>
                      onChange({
                        ...value,
                        [section.key]: value[section.key].filter(
                          (_: Entity, i: number) => i !== index,
                        ),
                      })
                    }
                  >
                    移除此条
                  </Button>
                )}
              </div>
              <div className="form-grid">
                {section.columns.map((column) => (
                  <Field
                    key={column.key}
                    label={`${section.title} ${index + 1} · ${column.label}`}
                    wide={column.wide}
                  >
                    {column.wide ? (
                      <textarea
                        disabled={disabled}
                        rows={2}
                        value={row[column.key] || ""}
                        onChange={(e) =>
                          updateRow(
                            section.key,
                            index,
                            column.key,
                            e.target.value,
                          )
                        }
                      />
                    ) : (
                      <input
                        disabled={disabled}
                        type={column.type || "text"}
                        value={row[column.key] || ""}
                        onChange={(e) =>
                          updateRow(
                            section.key,
                            index,
                            column.key,
                            e.target.value,
                          )
                        }
                      />
                    )}
                  </Field>
                ))}
              </div>
            </div>
          ))}
          {!disabled && (
            <Button
              type="button"
              icon="plus"
              onClick={() =>
                onChange({
                  ...value,
                  [section.key]: [
                    ...(value[section.key] || []),
                    Object.fromEntries(section.columns.map((c) => [c.key, ""])),
                  ],
                })
              }
            >
              新增{section.title}
            </Button>
          )}
          {disabled && !(value[section.key] || []).length && (
            <p className="muted">尚未录入此类记录。</p>
          )}
        </details>
      ))}
      <MaterialTests
        value={value.material_tests || []}
        onChange={(material_tests) => onChange({ ...value, material_tests })}
        disabled={disabled}
      />
      <div className="form-section-label">04 / 人工风险评估</div>
      <div className="form-grid">
        <Field
          label="风险等级"
          hint="由调查人员或修复师依据现场证据选择，不由软件自动推断。"
        >
          <select
            disabled={disabled}
            value={value.risk?.level || "unassessed"}
            onChange={(e) =>
              onChange({
                ...value,
                risk: { ...(value.risk || {}), level: e.target.value },
              })
            }
          >
            {Object.entries(riskLabels).map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="风险评估依据">
          <textarea
            disabled={disabled}
            rows={3}
            value={value.risk?.reason || ""}
            onChange={(e) =>
              onChange({
                ...value,
                risk: { ...(value.risk || {}), reason: e.target.value },
              })
            }
            placeholder="记录部位、发展迹象、检测证据及需要采取的措施。"
          />
        </Field>
      </div>
      <p className="muted">
        保存后由服务端记录评估人和时间。
        {value.risk?.assessed_by &&
          `当前记录评估人：${value.risk.assessed_by}。`}
        {!disabled && `本次操作身份：${user.name}。`}
      </p>
    </div>
  );
}
