# 实际验证记录 · 2026-10-28

本次验证证明代码与演示工作流可运行。测试数据是原创教学图、构造规则样例或离线服务响应，没有真实文物诊断准确率、真实云模型质量或机构试用结论。

## 环境和构建

- 项目Conda环境：`ArtifactHealthRecord/.conda`，Python3.11.18，Node22.23.4。
- PyTorch2.5.1+cpu、Transformers4.51.3、NumPy2.2.6、OpenCV4.11.0.86。
- `python3 run.py doctor` 确认Conda解释器、基础依赖、AI依赖及已构建前端存在。
- `pip check` 通过，没有损坏的依赖关系。当前完整版本快照在deploy目录。
- TypeScript检查与Vite生产构建通过，前端可由FastAPI同源提供。

## 后端、AI和适配器

最终执行命令（在项目Conda环境）：

```text
python3 -m pytest tests -q --junitxml=runtime/pytest-final.xml
```

结果：**94 passed，0 failed，0 skipped，6.24秒**。有1条Starlette/AnyIO接口弃用提示，不影响测试结果；依赖升级时需一起回归。

| 测试文件 | 用例数 | 主要证据 |
| --- | ---: | --- |
| test_workflow.py | 5 | API完整链路、权限、原始字节、几何与导出 |
| test_integrity.py | 18 | 旧方案失效、机构隔离、不可伪造模型来源、签名、历史快照、非法字段、原件缺失、排队模拟版本 |
| test_ai.py | 13 | 数据尺寸/重叠、分组防泄漏、指标空值、清单迁移、U-Net训练、SegFormer前向、配准与模拟 |
| test_rules.py | 25 | 十个构造冲突与十个对照，以及预算算术、否定语义、空鼓和引用边界 |
| test_generation.py | 7 | 离线MockTransport：非法输出回退、引用和章节、禁止AI签章、文本/视觉外发授权 |
| test_storage_cache.py | 26 | 本地原子文件、路径越界、OBS私有上传与错误/404/清理、Redis缓存及断连回退 |

详细分项见 `integrity-validation.json`、`storage-cache-validation.json`、`../ai/VALIDATION.json`；这些文件记录各自执行时刻的子集结果。最终总回归以本页和 `validation.json` 为准。

本执行环境对线程套接字有限制，沙盒内FastAPI TestClient会停滞；上述API回归经执行权限审核后在沙盒外运行，仍使用临时SQLite目录，没有访问外部模型或修改日常病历。此执行环境约束不代表普通本地运行需要管理员权限。

## 浏览器和实际服务

Playwright操作真实构建页面与临时后端，验证12条操作链：登录与看板、建档、上传、多边形原图坐标及面积、尺度、质量检查、抽取回退不自动保存、13部分方案与版本比较、规则与提交、模拟、独立专家审核、三种档案导出、资料审计和390px移动端。没有页面脚本错误或服务端5xx；记录在 `frontend-validation.json`，截图在 `runtime/screenshots/`。

最终本地服务在127.0.0.1:8765启动，健康检查通过；通过HTTP以演示修复师账号生成13节模板草案，并导出 `runtime/example-export/AHR-DEMO-001.{json,pdf,zip}`。ZIP清单中每个文件SHA-256均重新计算验证一致，包内无模拟图目录。

PDF模块另进行了中文文本提取、长方案14页分页、XML转义、SVG解析及图件栅格目检。原始字节和规范化图像分别保存，旧方案PDF使用生成时的事实快照。

## 模型工程训练

8张程序生成几何图，CPU紧凑U-Net训练2个epoch完成，checkpoint可重新加载。训练报告在 `runtime/ai-smoke/model/training.json`。该模型有冒烟标记，推理服务拒绝将它用于真实候选；真实评估脚本也拒绝合成样例。

真实六类Dice/IoU、检索Top-5/MRR、专家评分、效率提升和SUS均**未评测**。不能引用上述软件用例通过率替代这些指标。

## 未完成真实验收的部分

- RDS/PostgreSQL并发、Redis实际服务、OBS桶、MaaS/视觉模型线上响应和Docker容器：代码/配置或离线契约验证已交付，尚无实际资源验收。
- 20份完整授权病例、专业六类标注、LaMa/SD权重、正式标准图符核验和3家机构试点：需要真实资料、模型或专业合作。
- CodeArts实际调用、云端部署截图、比赛视频和正式签章：本次没有伪造相应证据。

这些项在 `guide-implementation-matrix.md` 中逐项对照原指南，可以作为后续真实项目验收清单。
