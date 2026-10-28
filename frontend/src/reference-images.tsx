import { useMemo, useState } from "react";
import { imageUrl, post, type Entity } from "./api";
import {
  Badge,
  Button,
  Empty,
  Field,
  LoadState,
  Modal,
  Panel,
  useAction,
  useApp,
  useLoad,
} from "./ui";

export function ReferenceImages() {
  const { data, loading, error, reload } = useLoad<Entity>("/reference-images");
  const { user } = useApp(),
    { act, busy } = useAction();
  const [query, setQuery] = useState(""),
    [selected, setSelected] = useState<Entity | null>(null),
    [page, setPage] = useState(0);
  const groups = useMemo(() => {
    const objects = new Map<string, Entity>();
    (data?.items || []).forEach((item: Entity) => {
      const key = String(item.artifact_id || item.id);
      if (!objects.has(key)) objects.set(key, { ...item, images: [] });
      objects.get(key)!.images.push(item);
    });
    return [...objects.values()].filter(
      (item) =>
        !query.trim() ||
        [
          item.title,
          item.title_zh,
          item.region,
          item.material,
          item.period,
          item.artifact_id,
        ]
          .join(" ")
          .toLocaleLowerCase()
          .includes(query.trim().toLocaleLowerCase()),
    );
  }, [data, query]);
  const importable = ["surveyor", "restorer", "admin"].includes(user.role);
  async function importObject(item: Entity) {
    await act(async () => {
      const record = await post(
        `/reference-images/${encodeURIComponent(item.artifact_id)}/import`,
      );
      window.location.hash = `records/${record.id}?tab=images`;
    }, "公开馆藏参考病历已建立；请人工补充病害标注，不将公开照片当作现场调查");
  }
  return (
    <Panel title="公开真实壁画参考图库" eyebrow="OPEN MUSEUM REFERENCE IMAGES">
      <LoadState loading={loading} error={error} retry={reload}>
        {data && (
          <>
            <p>
              {data.notice ||
                "来自公开馆藏的真实文物影像，按原始馆藏条目与许可保存。用于参考、标注练习与数据准备；不代表实地试点或已建立病害真值。"}
            </p>
            <div className="reference-toolbar">
              <Badge value="neutral">
                {data.artifact_count ?? groups.length} 件馆藏对象 /{" "}
                {data.image_count ?? data.items?.length ?? 0} 张影像
              </Badge>
              <Field label="筛选公开壁画参考图">
                <input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                  placeholder="按名称、年代、地区或材质搜索"
                />
              </Field>
            </div>
            {groups.length ? (
              <>
                <div className="provenance-image-grid">
                  {groups.slice(page * 6, page * 6 + 6).map((item) => (
                    <article
                      className="provenance-image-card"
                      key={item.artifact_id || item.id}
                    >
                      <button
                        className="reference-preview"
                        onClick={() => setSelected(item)}
                        aria-label={`预览真实影像 ${item.title_zh || item.title}`}
                      >
                        <img
                          src={imageUrl(item)}
                          alt={item.title_zh || item.title}
                          loading="lazy"
                        />
                      </button>
                      <div>
                        <Badge value="neutral">
                          真实馆藏影像 · {item.images.length} 张
                        </Badge>
                        <p>
                          封面：{item.view_type_label || "视图待核"}；收录：
                          {[
                            ...new Set(
                              item.images.map(
                                (image: Entity) =>
                                  image.view_type_label || "视图待核",
                              ),
                            ),
                          ].join(" / ")}
                        </p>
                        <h3>{item.title_zh || item.title}</h3>
                        {item.title_zh && item.title && <p>{item.title}</p>}
                        <p>
                          {[
                            item.region,
                            item.object_date || item.period,
                            item.material,
                          ]
                            .filter(Boolean)
                            .join(" / ")}
                        </p>
                        <p>
                          许可：
                          {item.license ||
                            item.provenance?.license_name ||
                            "查看逐图许可"}
                        </p>
                        {/^https?:\/\//i.test(item.source_url || "") && (
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            核对馆藏原始页面 ↗
                          </a>
                        )}
                        <div className="inline-actions">
                          <Button onClick={() => setSelected(item)}>
                            查看全部影像
                          </Button>
                          {importable && (
                            <Button
                              busy={busy}
                              variant="secondary"
                              onClick={() => importObject(item)}
                            >
                              导入参考病历
                            </Button>
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
                <div className="reference-pagination">
                  <Button
                    disabled={page === 0}
                    onClick={() => setPage((n) => n - 1)}
                  >
                    上一页
                  </Button>
                  <span>
                    第 {page + 1} / {Math.ceil(groups.length / 6)} 页 ·{" "}
                    {groups.length} 件对象
                  </span>
                  <Button
                    disabled={(page + 1) * 6 >= groups.length}
                    onClick={() => setPage((n) => n + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </>
            ) : (
              <Empty
                title="暂无匹配的真实参考影像"
                description="公开图像需要实际下载和核对许可后才显示在这里。"
              />
            )}
          </>
        )}
      </LoadState>
      {selected && (
        <Modal
          title={selected.title_zh || selected.title}
          onClose={() => setSelected(null)}
        >
          <p className="callout compact">
            公开馆藏照片不提供现场敲击、含水率、盐分等检测结果。导入后以公开参考病历保存，病害判断仍须明确证据与局限。
          </p>
          {selected.images.map((item: Entity) => (
            <figure className="reference-full-image" key={item.id}>
              <img src={imageUrl(item)} alt={item.title_zh || item.title} />
              <figcaption>
                {item.view_type_label || "馆藏影像"} · {item.width} ×{" "}
                {item.height} px ·{" "}
                {item.provenance?.creator || "作者见原始馆藏条目"} ·{" "}
                {item.license || item.provenance?.license_name}
              </figcaption>
            </figure>
          ))}
          {importable && (
            <Button
              busy={busy}
              variant="primary"
              onClick={() => importObject(selected)}
            >
              将该对象的全部影像导入参考病历
            </Button>
          )}
        </Modal>
      )}
    </Panel>
  );
}
