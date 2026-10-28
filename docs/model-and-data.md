# 数据与模型 · xqw-v0

先明确三件事：真实照片、专家病害标注、完整修复病例是三种不同资产。现在取得了可公开随代码交付的中国壁画照片，原有本机研究图也在；**六类病害标注和完整修复病例尚缺**，因此不能训练后声称达到项目书目标。

## 实际数据账目

最终公开包的数量以 `data/public/mural_reference/manifest.json` 为准。对象来自The Met官方开放馆藏，保留JPEG原字节、逐图SHA-256、对象编号、标题、地区、材质、年代、视图类别、公开许可与18份官方API元数据。已人工排除馆方线描说明图；彩色正面、黑白旧照、背面/装裱结构分开登记。背面及同件多视图不是新的壁画。

这些图属于中国馆藏壁画，含山西、新疆及原址待核对象，**不能改称甘肃现场训练集**。尚无六类真值、实测比例尺、色卡、拍摄日期、盐分/空鼓检测或修复过程。`training_eligible=false`、`expert_reviewed=false`；只能先用于真实图像展示、标注操作与通用模型工程验证。分组采取保守原址规则，不以馆藏编号自动推定样本独立。

本机 `runtime/real-data/dunhuang_hf` 有60张研究GT裁片，清单固定了来源版本和SHA；GT属于原研究任务，并非本项目的六类病害标签。镜像数据卡的MIT声明尚不能证明逐图完整权利链，故不上传公开仓库；所有裁片保守归同一原始来源组，不用于独立测试。

MuralDH已有下载器、固定文件大小/哈希与访问报告（`ai/DATA_ACCESS.json`）。现有记录未取得完整数据包。官方访问受限需正常授权下载，再使用 `scripts/download_data.py --local-archive` 验证；不能把其他公开图改名为MuralDH，也不能自动套用其分类。

## 数据准备与人工审核

1. 团队与目标地域单位确认用途、公开范围及保密要求，采集30–50张目标壁画局部图，并记录原壁画/遗址关系。
2. 使用 `data/templates/` 采集模板登记。比例尺、色卡、相机、照明、拍摄时间与检测报告必须来自实际采集，未知留空。
3. 六类各至少20实例是初赛采集目标（六类合计至少120），后续按项目书质控目标扩大；不是当前已达数量。
4. 两人独立标注、第三人仲裁。LabelMe用固定中文名称，不确定区域 `flags.uncertain=true`；空鼓/酥碱另有现场证据。运行 `scripts/evaluate_study.py --inter-rater 人员A=mask_a.png 人员B=mask_b.png --output runtime/rater-report.json`，低一致性样本回到定义与仲裁。
5. `scripts/prepare_dataset.py`生成PNG与独立多类NPZ，原图、PNG、NPZ均绑定SHA；不确定和重叠区域不当作健康背景。按原壁画或遗址先分组再切片，合成图只训练。

```console
python3 run.py script prepare_dataset.py --annotations data/annotations --groups data/groups.csv --output data/prepared --group-by site_id --seed 42
```

groups.csv中的 `image,site_id,mural_id,data_kind,license,reviewed` 必须来自实际审查；`reviewed=true`不能由程序替代专家工作。新公开参考图清单不自动输入这个训练入口。

## 完整模型路径

现有代码支持紧凑U-Net、SMP预训练ResNet34 U-Net、SegFormer-B0；紧凑U-Net用于工程基线，不冒充ResNet34。二分类、六类、编码器冻结、同架构迁移、滑窗与五折保持完整。损失仍为0.5交叉熵+0.5 Dice，忽略255；默认超参数来自既有工程/项目书配方，未经真实目标域寻优。

```console
python3 run.py setup --with-ai
python3 run.py script fetch_models.py --models dinov2 sam resnet34
python3 run.py script train.py --help
python3 run.py script evaluate.py --help
```

安装入口已修复为读取**完整** `requirements-ai.txt`，避免仅装torch/transformers却漏torchvision/SMP。正式训练须真实独立验证集；不能拿工程合成数据生成可上线的六类权重。推理服务拒绝smoke/synthetic-only模型。

SAM与DINOv2是已下载的通用预训练模型：前者根据点击提区域，后者比较图像特征。它们既不输出可靠病害诊断，也不提供完整病例。真实权重和真图推理的结果、版本与耗时在 `../ai/REAL_ASSET_VALIDATION.json`；没有将工程成功改写为Dice或专家相关性成绩。

## 数据预处理、模拟与外部服务

`ai/preprocessing.py`提供色卡仿射校色、相机内参去畸变、重叠拼接和切片。它保存独立派生目录和操作清单，原图不覆盖；缺真实相机/色卡参数不虚构校正。拼接改变坐标系，需重新标注。

默认模拟为OpenCV Telea插值，带永久水印并与正式档案隔离；LaMa和Stable Diffusion仍需合法本地权重及实际验收。前后图配准输出像素变化，不等于疗效。

RAG、VLM与embedding配置需要真实服务及外发授权；无凭据走明确的模板/人工路径。MaaS云端实测、目标域训练和专家盲评是独立未完成项。

## E1–E6验收

E1按组隔离、按类报Dice/IoU/Precision/Recall、混淆矩阵和最差20样本；五折必须完整，不报最佳折冒充均值。E2–E6的空采集表和统计器由 `scripts/evaluate_study.py` 生成/运行，包含SUS原始十题、配对、样本标准差和bootstrap区间。没有真实观察则状态为 `awaiting_observations`，不填项目书中的示例分数。

公开真实样例哈希可离线复查：

```console
python3 run.py verify
```

所有模型置信分数、图像质量阈值和配准阈值延续既有设置，属于工程参数；专业适用性需真实数据标定。Word给出每项缺口的材料、责任角色与完成标准。
