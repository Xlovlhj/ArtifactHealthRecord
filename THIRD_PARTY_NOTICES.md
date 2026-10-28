# 第三方资产、许可与原创范围

应用业务代码、测试、自撰文档和程序化教学图按根目录MIT许可证提供。外部资料、照片、模型和数据集不因代码许可证而改变授权。

| 资产 | 版本/来源 | 用途与修改 | 分发范围 |
| --- | --- | --- | --- |
| The Met开放馆藏影像 | `data/public/mural_reference/source_lock.json`固定原件SHA与URL；2026-10-28核验 | 27张实物照片/18件，14彩色正面、5黑白正面、8背面；保留馆方JPEG字节，自编中文说明/视图分类 | 馆方CC0开放，包含原图及18份官方对象元数据；许可证据见manifest |
| FastAPI / SQLAlchemy / Pydantic / HTTPX等 | `requirements.txt`固定版本 | API、数据模型、持久化；未复制第三方完整应用 | 依赖按各包上游许可安装，不内嵌依赖环境 |
| Pillow / NumPy / OpenCV / ReportLab | `requirements.txt`固定版本 | 影像、几何、导出及原创教学图 | 按各包许可安装 |
| React / TypeScript / Vite | `frontend/package-lock.json` | 项目自有界面；没有复制博物馆网页 | 按各包许可安装；保留打包器相关声明 |
| PyTorch / torchvision / SMP / timm / Transformers | `requirements-ai.txt` | U-Net、ResNet34、SegFormer、SAM、图像检索适配，业务与评测为本项目实现 | 不分发第三方库或模型二进制 |
| DINOv2 / SAM | `scripts/fetch_models.py`固定上游revision与权重SHA | 通用视觉特征/点选边界；未冒充文物专用权重；未微调 | 官方模型卡许可信息由下载器记录，权重本机runtime保存，不进Git |
| ResNet34 ImageNet编码器 | PyTorch官方resnet34-b627a593.pth | 预训练编码器及SMP U-Net；不等于经过病害训练 | 按官方权重来源及条件获取，权重不进Git |
| LaMa / Stable Diffusion | 可选用户本地权重 | 沟通模拟适配；本次无权重专业验收 | 不分发；使用者须核对具体模型许可 |
| 华为OBS SDK / psycopg / Redis客户端 | requirements固定版本 | OBS、PostgreSQL/RDS、Redis缓存适配 | 按上游各自许可安装 |
| 标准、规范、公开文保材料 | `data/knowledge/sources.json`及manifest | 自撰摘要、事实字段、章节和图示参数，保留出处 | 不分发有水印/受限标准全文；参数核验不等于输出认证 |
| MuralDH | [Dryad发布页](https://datadryad.org/dataset/doi:10.5061/dryad.bnzs7h4jd) | 元数据及下载核验程序；完整包未取得 | 未分发真实原始包；数据CC0声明不推及作者代码 |
| 敦煌研究GT镜像 | 本机runtime/real-data/dunhuang_hf固定清单 | 60张原图裁片，六类标签0，逐图完整权利链未充分核实 | 不上传公开仓库；GT含义不能改写成本项目病害真值 |
| python-docx | requirements-docs.txt | 生成Word交付报告 | 可选文档依赖，非服务运行必需 |

照片许可证据：[The Met Open Access](https://www.metmuseum.org/hubs/open-access)、各对象API的`isPublicDomain=true`及`metadata_sha256`，详见公开包。将照片缩小显示在页面/Word中不改动交付原件。馆方线描说明图未混入照片数量。

项目截图包含原创教学夹具和明确标注来源的开放照片；不包含受限现场影像、专家私人信息、真实云凭据或模型密钥。后续接入合作单位数据时，按协议选择公开范围，不能因为可在本机查看而自动加入发布包。
