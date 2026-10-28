# 图像与模型子系统

本模块实现真实可训练的 U-Net / 预训练ResNet34 U-Net / SegFormer、SAM交互辅助、DINOv2/CLIP图像检索、LabelMe数据准备、原图分辨率滑窗推理、按遗址/壁画隔离的评测、照片配准与带水印模拟。没有已验证权重时，服务只做采集质量检查并返回空病害候选；人工标注流程可继续。

2026-10-28 已核查中国矿业大学团队发布的 [MuralDH](https://datadryad.org/dataset/doi:10.5061/dryad.bnzs7h4jd)。Dryad API 明确给出 CC0-1.0，原包 7.74 GB。当前环境中公开下载返回 403、API 下载返回 401，尚未取得原始标注，因此没有可报告的真实病害 Dice，也没有将工程测试模型启用为诊断模型。本轮重新检查仍为401/403，逐项记录见 [数据盘点](DATA_INVENTORY.json)；早期记录保留在 `DATA_ACCESS.json`。MuralDH 原标签与目标六类不相同，下载后也必须先人工核对标签、来源组及许可，不能强行映射。

## 实际取得的影像与真实运行证据

公开包 [manifest.json](../data/public/mural_reference/manifest.json) 包含 **27张实物照片、18件馆藏对象**：14张彩色正面、5张黑白正面、8张背面/装裱结构。全部来自 The Met 官方开放API，逐件 `isPublicDomain=true`，依据[馆方CC0政策](https://www.metmuseum.org/hubs/open-access)随仓库分发。保存原始JPEG、18份官方对象元数据、来源链接、许可及SHA256；下载脚本按 `source_lock.json` 固定字节核验。已排除一张馆方线描说明图，不把它算作摄影图像。

照片用于真实影像显示、辅助标注操作及检索工程验证。它们没有本项目六类病害标签，部分是黑白旧照和背面，不能替代目标地域现场采集。18个馆藏号不证明18个原址独立组；除已证实的广胜寺外，其余原址关系待核，采取保守同组。

本机 `runtime/real-data/dunhuang_hf` 另有60张真实研究GT裁片，已逐张核SHA256；GT是上游图像修复参考图，不是六类病害真值。它们保守归为莫高窟第7窟同组，第三方镜像未给出逐图完整权利链，因此不纳入GitHub发行包。六类专家标注、真实六类检查点和真实测试Dice均尚未取得。

[本轮真实模型运行报告](REAL_ASSET_VALIDATION.json) 使用公开广胜寺实物照片运行官方本地DINOv2 Top5检索、SAM点提示和ResNet34预训练编码器前向。报告记录输入/权重/预处理配置SHA256、CPU/float32、时间与实际输出。SAM不自动分配病害类，DINO分数是视觉余弦相似度；ResNet34分割头仍未训练。此前 `VALIDATION.json` 是早期历史记录，不能代替本轮证据。

## 与指南的对应和新增实现

- 沿用六类病害加背景、U-Net/SegFormer、CE + Dice、AdamW、6e-5 学习率、0.01 权重衰减、80 epochs、patience=10。损失两个分量各 0.5，与指南代码骨架一致。
- 当前训练CLI默认 `unet-resnet34`；若未指定 `--pretrained/--resume/--transfer`，自动采用已下载的 `runtime/models/resnet34/resnet34-b627a593.pth`。缺少该文件时，正式训练会报错并给出下载入口。`segformer-b0` 须显式选择，并提供本地目录或Hub预训练模型ID才能使用预训练编码器。本轮未修改这些既有默认行为。
- 保留原有自编紧凑 `unet`（三层下采样，默认基础通道 16，随机初始化），用于当前 CPU 条件下的管线验证和可选基线。它不是指南中的预训练 ResNet34，不能将运行成功或合成损失当作病害精度。
- 修复指南示例将 `Image.size` 的宽高读反的问题；按真实 `(width,height)` 保存 mask。
- 六类可共存，七分类 softmax 不能表达同像素多类。转换时独立六通道存入NPZ，PNG与NPZ均绑定清单SHA256，重叠/不确定像素在单标签 PNG 中为 255 并从损失/指标排除；不会让后画的病害覆盖前一类。采用完整多标签训练需另行设计和验证。
- 默认按遗址分组更保守，也可选壁画；必须提供核实后的 `site_id/mural_id`。相同图像 SHA256 不得跨训练、验证、测试，合成衍生图不能跨原真实组。
- 数据清单保存相对图像/mask路径，搬迁完整数据目录结构后仍可加载，清单哈希不因工作区绝对路径改变。
- 保守实现成对裁剪、水平翻转；不改变色相和饱和度。未声称已完成指南的全部增强参数消融。
- LaMa 和本地 Stable Diffusion 是可配置推理入口。默认新增 OpenCV Telea 插值预览用于闭环操作验证，明确显示 **非学习模型**，不声称复原历史原貌。已选学习模型但缺少权重时直接报错，不静默冒充成功。

## Conda 内运行

从项目根目录执行。环境由项目根目录启动工具管理；以下命令均在该环境激活后运行，不使用 shell 启动脚本。

```console
conda activate ./.conda
python3 scripts/download_data.py
```

默认仅核查和保存数据元信息。确实需要下载 7.74 GB 完整包时使用 `python3 scripts/download_data.py --download`。若官方平台需要登录，在用户完成正常下载后执行 `python3 scripts/download_data.py --local-archive /path/to/MuralDH.zip` 验证已核实版本的尺寸和 SHA256。该命令不会自动解压或绕过认证。

`python3 run.py setup --with-ai` 安装 `requirements-ai.txt` 固定的PyTorch CPU、torchvision、SMP、Transformers及影像依赖。Stable Diffusion另需可选的 `diffusers/accelerate/safetensors`。代码不在启动时自动安装包或下载模型。

## 准备经过审核的真实数据

LabelMe 图像与同名 JSON 放入一个目录。标签严格限定为 `起甲、酥碱、空鼓、裂隙、颜料层脱落、地仗脱落`。每个 shape 为原图像素坐标多边形；不确定区域用 `flags.uncertain=true`。非标准 EXIF 旋转必须先统一图像方向并重新核对标注，避免坐标错位。

建立 `groups.csv`，不能从编号猜测洞窟/壁画来源。示例只解释格式，并不代表已经取得这些真实数据：

```csv
image,site_id,mural_id,data_kind,license,reviewed
cave_a/image_001.png,VERIFIED_SITE_A,VERIFIED_MURAL_1,real,实际许可编号,true
cave_b/image_002.png,VERIFIED_SITE_B,VERIFIED_MURAL_2,real,实际许可编号,true
cave_c/image_003.png,VERIFIED_SITE_C,VERIFIED_MURAL_3,real,实际许可编号,true
```

```console
python3 scripts/prepare_dataset.py --annotations data/annotations --groups data/groups.csv --output data/prepared --group-by site_id
python3 scripts/fetch_models.py --models resnet34
python3 scripts/train.py --manifest data/prepared/manifest.json --output runtime/models/baseline --device cpu
python3 scripts/evaluate.py --manifest data/prepared/manifest.json --checkpoint runtime/models/baseline/best.pt --output runtime/evaluation/baseline
```

至少三个独立真实组才分离训练、验证、测试，实际研究应增加组数。默认近似 70/15/15 按组划分，受小整数样本影响不保证逐图比例。五折通过 `--folds 5 --fold 0` 到 `--fold 4` 分别生成清单和训练。完成每折测试后，用 `python3 scripts/evaluate.py --aggregate fold0/metrics.json fold1/metrics.json fold2/metrics.json fold3/metrics.json fold4/metrics.json --output runtime/evaluation/five-fold` 汇总；校验测试组无重复、架构相同并输出样本标准差。未运行的五折标准差保持 `null`。

预训练两种路线示例：

```console
python3 scripts/train.py --manifest data/prepared/manifest.json --model unet-resnet34 --pretrained imagenet --output runtime/models/resnet34
python3 scripts/train.py --manifest data/prepared/manifest.json --model segformer-b0 --pretrained /path/to/authorized-local-segformer-b0 --output runtime/models/segformer
```

`--resume` 只加载本项目同架构权重用于继续微调，不恢复优化器时钟；训练报告记录参数和数据摘要。FastAPI应用通过 `.env` 中的 `AHR_SEGMENTATION_CHECKPOINT` 指向 `best.pt`；直接调用AI模块时可显式传checkpoint参数或使用该模块的 `AHR_MODEL_CHECKPOINT` 环境变量。输入颜色归一化在训练和推理一致。阈值 0.5 只是未标定候选显示默认值，必须由独立验证与专家选择真正工作点。

评测使用原图分辨率滑窗，报告每类 Dice/IoU/precision/recall/F1、宏平均、混淆矩阵、CPU 推理时间及最多 20 个最差样本预测图。两边都不存在的类别是 `null`，不计作满分；报告同时给出实际覆盖类别数，以及逐图和总体的 `ignored_fraction`。重叠/不确定区域被排除，忽略比例过高会限制指标代表性，不能只看Dice。空鼓的视觉预测始终要求现场证据。未知面积标尺时仅输出像素量，绝不虚构平方厘米。

## 真图与辅助模型复现

先按前文进入项目Conda环境，再执行：

```console
python3 scripts/fetch_public_murals.py
python3 scripts/fetch_models.py --models dinov2 sam resnet34
python3 scripts/verify_real_assets.py
```

第一条在文件齐全时核验并复用公开包，缺失文件时从固定官方URL下载；不生成替代图。第二条显式取得通用预训练权重，权重不进入Git。第三条在真实图上实测并生成 `ai/REAL_ASSET_VALIDATION.json`。检索版本同时绑定网络权重与图像预处理配置；修改缩放/归一化配置会使版本及特征缓存失效。

采集登记和双人独立标注/第三人仲裁的空表在 [data/templates](../data/templates/)。参考图库的 [annotation_intake.csv](../data/public/mural_reference/annotation_intake.csv) 已填来源和SHA，标注者及审核字段保持空白。独立标注者掩膜可用 `python3 scripts/evaluate_study.py --inter-rater A=/path/a.png B=/path/b.png --output runtime/annotation_agreement.json` 按指南逐类计算Dice；争议仍由专家仲裁。

## 仅验证工程链路的可复现样例

下面生成的是规则几何色块，不是敦煌壁画，也不是经过专家验证的病害仿真。样例只进训练，无验证/测试集。

```console
python3 scripts/prepare_dataset.py --make-smoke-data runtime/ai-smoke/data
python3 scripts/train.py --manifest runtime/ai-smoke/data/prepared/manifest.json --output runtime/ai-smoke/model --model unet --base-channels 4 --size 64 --epochs 2 --batch-size 2 --threads 2 --smoke-test
python3 -m pytest tests/test_ai.py -q
```

冒烟权重带 `smoke_test=true` 和 `synthetic_only=true`。`analyze_image` 拒绝用这些权重生成病害候选，`evaluate.py` 拒绝将它们用于真实效果报告。需要真实标注与现场审核才能补齐最后的实证性能。

## 服务边界

`analyze_image(path, checkpoint=None)` 返回原图宽高、采集质量检查、候选区域、模型版本、运行状态及限制。没有权重时 `mode=manual_required`、`status=model_unavailable`、`predictions=[]`。

`compare_images(before, after)` 以 ORB + RANSAC 在近似平面进行配准，返回单应矩阵、重叠比例及带颜色的像素差异图 data URL。可靠特征不足即失败，不输出差异百分比。像素变化可能来自照明/相机/遮挡，不能解释为病害改善或加重。RANSAC 4px、比值0.75、至少8个一致点、25%重叠及25/255变化阈值均为明确工程默认值，不是文物标准。

`simulate(image, mask, output, method=None, checkpoint=None)` 保持原文件不变、仅在掩膜内生成内容，然后在输出底部永久添加英文模拟水印。LaMa 支持可信本地 TorchScript 模型，其调用契约为 `model(image_NCHW, mask_N1HW) -> RGB_NCHW` 或 `{'inpainted': RGB_NCHW}`，需导出与该契约一致的权重；原仓库 checkpoint 不能直接当该导出文件。Stable Diffusion 只读本地 Diffusers 目录。二者尚无授权权重时不声称经过端到端学习模型测试。

参考：[MuralDH 论文](https://doi.org/10.1038/s41597-024-03785-0)、[Dryad 许可条款](https://datadryad.org/terms)、[SegFormer 官方文档](https://huggingface.co/docs/transformers/model_doc/segformer)、[LaMa 原项目](https://github.com/advimman/lama)。上游算法名与项目新增的业务约束、分组校验、接口、模拟回退、测试已分别注明。
