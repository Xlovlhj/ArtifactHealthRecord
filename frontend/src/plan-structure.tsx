import type { Entity } from "./api";
import { Badge, Button, Field, Value } from "./ui";
const categories: Record<string, string> = {
  environment: "环境调查与控制",
  investigation: "调查检测",
  trial: "材料与工艺试验",
  body: "本体保护修复",
  monitoring: "监测与后续保护",
};
export function MeasuresEditor({
  value,
  onChange,
  editing,
}: {
  value: Entity[];
  onChange: (value: Entity[]) => void;
  editing: boolean;
}) {
  function update(index: number, key: string, data: any) {
    onChange(
      value.map((item, i) => (i === index ? { ...item, [key]: data } : item)),
    );
  }
  function move(index: number, direction: number) {
    const items = [...value];
    [items[index], items[index + direction]] = [
      items[index + direction],
      items[index],
    ];
    onChange(items);
  }
  return (
    <div className="plan-structured">
      <h3>有序工序与前置条件</h3>
      <p className="muted">
        按拟执行顺序组织调查、环境控制、材料筛选和本体处理。规则检查使用这些结构化工序；排序与前置条件需人工核对。
      </p>
      {value.length ? (
        value.map((item, index) => (
          <div className="structured-row" key={item.id || index}>
            <div className="structured-row-heading">
              <b>
                {index + 1}. {item.name || "待填写工序"}
              </b>
              <Badge value="neutral">
                {categories[item.category] || item.category || "未分类"}
              </Badge>
              {editing && (
                <div className="inline-actions">
                  <Button
                    type="button"
                    aria-label={`上移工序${index + 1}`}
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    type="button"
                    aria-label={`下移工序${index + 1}`}
                    disabled={index === value.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    icon="trash"
                    onClick={() =>
                      onChange(value.filter((_, i) => i !== index))
                    }
                  >
                    删除工序
                  </Button>
                </div>
              )}
            </div>
            {editing ? (
              <div className="form-grid">
                <Field label={`工序${index + 1} · 名称`}>
                  <input
                    value={item.name || ""}
                    onChange={(e) => update(index, "name", e.target.value)}
                  />
                </Field>
                <Field label={`工序${index + 1} · 类型`}>
                  <select
                    value={item.category || "investigation"}
                    onChange={(e) => update(index, "category", e.target.value)}
                  >
                    {Object.entries(categories).map(([key, name]) => (
                      <option value={key} key={key}>
                        {name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={`工序${index + 1} · 前置工序`} wide>
                  <div className="checkbox-grid">
                    {value
                      .filter((step) => step.id !== item.id)
                      .map((step) => (
                        <label className="check-field" key={step.id}>
                          <input
                            type="checkbox"
                            checked={(item.prerequisites || []).includes(
                              step.id,
                            )}
                            onChange={(e) =>
                              update(
                                index,
                                "prerequisites",
                                e.target.checked
                                  ? [...(item.prerequisites || []), step.id]
                                  : (item.prerequisites || []).filter(
                                      (id: string) => id !== step.id,
                                    ),
                              )
                            }
                          />
                          {step.name || step.id}
                        </label>
                      ))}
                  </div>
                  {(item.prerequisites || [])
                    .filter(
                      (id: string) => !value.some((step) => step.id === id),
                    )
                    .map((id: string) => (
                      <label className="check-field" key={id}>
                        <input
                          type="checkbox"
                          checked
                          onChange={() =>
                            update(
                              index,
                              "prerequisites",
                              item.prerequisites.filter(
                                (key: string) => key !== id,
                              ),
                            )
                          }
                        />
                        引用了已移除工序：{id}（取消勾选以清除）
                      </label>
                    ))}
                </Field>
                <Field label={`工序${index + 1} · 材料类别`}>
                  <input
                    value={item.material_category || ""}
                    onChange={(e) =>
                      update(index, "material_category", e.target.value)
                    }
                    placeholder="仅类别与筛选要求，不生成配比"
                  />
                </Field>
                <Field label={`工序${index + 1} · 引用ID`}>
                  <input
                    value={(item.citations || []).join(", ")}
                    onChange={(e) =>
                      update(
                        index,
                        "citations",
                        e.target.value.split(/[,，\s]+/).filter(Boolean),
                      )
                    }
                    placeholder="用逗号分隔证据 ID"
                  />
                </Field>
                <Field label={`工序${index + 1} · 风险`} wide>
                  <textarea
                    rows={2}
                    value={item.risk || ""}
                    onChange={(e) => update(index, "risk", e.target.value)}
                  />
                </Field>
                <Field label={`工序${index + 1} · 不确定性`} wide>
                  <textarea
                    rows={2}
                    value={item.uncertainty || ""}
                    onChange={(e) =>
                      update(index, "uncertainty", e.target.value)
                    }
                  />
                </Field>
              </div>
            ) : (
              <div className="operation-read">
                <p>
                  <b>前置条件：</b>
                  {(item.prerequisites || []).length
                    ? item.prerequisites
                        .map(
                          (id: string) =>
                            value.find((step) => step.id === id)?.name || id,
                        )
                        .join("、")
                    : "无已登记前置工序"}
                </p>
                <p>
                  <b>材料类别：</b>
                  <Value value={item.material_category} />
                </p>
                <p>
                  <b>风险：</b>
                  <Value value={item.risk} />
                </p>
                <p>
                  <b>不确定性：</b>
                  <Value value={item.uncertainty} />
                </p>
                <p>
                  <b>依据 ID：</b>
                  {(item.citations || []).join("、") || "尚未登记引用"}
                </p>
              </div>
            )}
          </div>
        ))
      ) : (
        <p className="muted">
          尚无结构化工序。请在修订模式中补充，单独的正文描述不足以检查先后关系。
        </p>
      )}
      {editing && (
        <Button
          type="button"
          icon="plus"
          onClick={() =>
            onChange([
              ...value,
              {
                id: `M-${Date.now()}-${value.length + 1}`,
                name: "",
                category: "investigation",
                prerequisites: [],
                material_category: "",
                citations: [],
                risk: "",
                uncertainty: "",
              },
            ])
          }
        >
          新增工序
        </Button>
      )}
    </div>
  );
}
export function BudgetEditor({
  value,
  onChange,
  editing,
}: {
  value: Entity[];
  onChange: (value: Entity[]) => void;
  editing: boolean;
}) {
  function update(index: number, key: string, data: any) {
    onChange(
      value.map((row, i) => (i === index ? { ...row, [key]: data } : row)),
    );
  }
  return (
    <div className="plan-structured">
      <h3>工程量与预算明细</h3>
      <p className="muted">
        数量、单价与出处按真实计量和报价填写；服务端检查显式算术关系，软件不补造价格。
      </p>
      <div className="table-wrap">
        <table className="budget-table">
          <thead>
            <tr>
              <th>项目</th>
              <th>数量</th>
              <th>单位</th>
              <th>单价（元）</th>
              <th>合计（元）</th>
              <th>计量 / 报价依据</th>
              {editing && <th />}
            </tr>
          </thead>
          <tbody>
            {value.map((row, index) => (
              <tr key={index}>
                {[
                  "item",
                  "quantity",
                  "unit",
                  "unit_price",
                  "total",
                  "source",
                ].map((key) => (
                  <td key={key}>
                    {editing ? (
                      <input
                        aria-label={`预算${index + 1} · ${({ item: "项目", quantity: "数量", unit: "单位", unit_price: "单价", total: "合计", source: "依据" } as Entity)[key]}`}
                        type={
                          ["quantity", "unit_price", "total"].includes(key)
                            ? "number"
                            : "text"
                        }
                        min="0"
                        step="any"
                        value={row[key] ?? ""}
                        onChange={(e) =>
                          update(
                            index,
                            key,
                            ["quantity", "unit_price", "total"].includes(key)
                              ? e.target.value === ""
                                ? null
                                : Number(e.target.value)
                              : e.target.value,
                          )
                        }
                      />
                    ) : (
                      <Value value={row[key]} />
                    )}
                  </td>
                ))}
                {editing && (
                  <td>
                    <Button
                      type="button"
                      variant="danger"
                      icon="trash"
                      aria-label={`删除预算${index + 1}`}
                      onClick={() =>
                        onChange(value.filter((_, i) => i !== index))
                      }
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!value.length && <p className="muted">尚未录入经核对的工程量与报价。</p>}
      {editing && (
        <Button
          type="button"
          icon="plus"
          onClick={() =>
            onChange([
              ...value,
              {
                item: "",
                quantity: null,
                unit: "",
                unit_price: null,
                total: null,
                source: "",
              },
            ])
          }
        >
          新增预算项
        </Button>
      )}
    </div>
  );
}
