import { type Entity } from "./api";
import { Button, Field } from "./ui";
const metrics = [
  ["ph", "pH"],
  ["color_difference", "色差 ΔE"],
  ["gloss_difference", "光泽差"],
  ["penetration_depth_mm", "渗透深度（mm）"],
  ["vapor_permeability_ratio_pct", "透气率比（%）"],
  ["porosity_reduction_pct", "孔隙率减少量（%）"],
  ["adhesive_strength_mpa", "粘接强度（MPa）"],
  ["surface_temperature_c", "表面温度（℃）"],
  ["relative_humidity_pct", "相对湿度（%）"],
];
export function MaterialTests({
  value,
  onChange,
  disabled = false,
}: {
  value: Entity[];
  onChange: (items: Entity[]) => void;
  disabled?: boolean;
}) {
  function update(index: number, key: string, data: any) {
    onChange(
      value.map((row, i) => (i === index ? { ...row, [key]: data } : row)),
    );
  }
  return (
    <details className="structured-section" open={value.length > 0}>
      <summary>
        材料筛选与现场小试<span className="count-pill">{value.length}</span>
      </summary>
      <p className="muted">
        录入真实测量及报告出处。WW/T 0113—2023
        中的起甲粘接材料试验与现场小试按各自适用范围检查，未测项目留空；结果不扩展为所有壁画材料的通用阈值。
      </p>
      {value.map((row, index) => (
        <div className="structured-row" key={index}>
          <div className="structured-row-heading">
            <b>材料试验 · {index + 1}</b>
            {!disabled && (
              <Button
                type="button"
                variant="danger"
                icon="trash"
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              >
                删除试验
              </Button>
            )}
          </div>
          <div className="form-grid">
            <Field label={`材料试验 ${index + 1} · 日期`}>
              <input
                type="date"
                value={row.date || ""}
                disabled={disabled}
                onChange={(e) => update(index, "date", e.target.value)}
              />
            </Field>
            <Field label={`材料试验 ${index + 1} · 材料类别`}>
              <input
                value={row.material_category || ""}
                disabled={disabled}
                onChange={(e) =>
                  update(index, "material_category", e.target.value)
                }
              />
            </Field>
            <Field label={`材料试验 ${index + 1} · 适用范围`} wide>
              <select
                value={row.scope || "flaking_adhesive_test"}
                disabled={disabled}
                onChange={(e) => update(index, "scope", e.target.value)}
              >
                <option value="flaking_adhesive_test">
                  起甲粘接材料筛选试验
                </option>
                <option value="flaking_site_trial">起甲保护现场小试</option>
              </select>
            </Field>
            <Field label={`材料试验 ${index + 1} · 方法 / 仪器`} wide>
              <textarea
                rows={2}
                value={row.method || ""}
                disabled={disabled}
                onChange={(e) => update(index, "method", e.target.value)}
              />
            </Field>
            {metrics.map(([key, label]) => (
              <Field key={key} label={`材料试验 ${index + 1} · ${label}`}>
                <input
                  type="number"
                  step="any"
                  value={row.values?.[key] ?? ""}
                  placeholder="未测定"
                  disabled={disabled}
                  onChange={(e) => {
                    const values = { ...(row.values || {}) };
                    if (e.target.value === "") delete values[key];
                    else values[key] = Number(e.target.value);
                    update(index, "values", values);
                  }}
                />
              </Field>
            ))}
            <Field label={`材料试验 ${index + 1} · 报告出处`} wide>
              <input
                value={row.source || ""}
                disabled={disabled}
                onChange={(e) => update(index, "source", e.target.value)}
                placeholder="报告编号、档案条目或可核对的原始来源"
              />
            </Field>
          </div>
        </div>
      ))}
      {!disabled && (
        <Button
          type="button"
          icon="plus"
          onClick={() =>
            onChange([
              ...value,
              {
                date: "",
                material_category: "",
                scope: "flaking_adhesive_test",
                method: "",
                values: {},
                source: "",
              },
            ])
          }
        >
          新增材料试验
        </Button>
      )}
      {disabled && !value.length && (
        <p className="muted">尚未录入材料试验数据。</p>
      )}
    </details>
  );
}
