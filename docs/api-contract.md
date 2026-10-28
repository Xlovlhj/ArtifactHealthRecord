# 文物病历 API 协议 v1

Base `/api/v1`，JSON。登录使用 HttpOnly 同站 cookie，fetch 默认 credentials same-origin；开发代理 /api 到 8765。所有返回错误 `{detail: string | object}`。数字仅用于真实计算，未评测值 null。

- POST `/auth/login` `{username,password}` -> `{user:{id,name,username,role,org},access_token}`；POST `/auth/logout`；GET `/auth/me`。演示用户名 `surveyor/restorer/expert/manager/admin`，演示密码由启动时 runtime/demo-access.json 提供，默认本地演示 `ahr-demo-2026`。UI展示切换身份且允许输入密码。role=surveyor/restorer/expert/manager/admin。
- GET `/health` -> `{status,version,database,llm,segmentation,storage,redis,demo_mode}`。
- GET `/dictionary` -> `{diseases:[{type,color,standard_code,requires_field_evidence}],plan_sections:[{key,title}],rules_version,standards:[...]}`。
- GET `/dashboard` -> `{records,images,diseases,plans,pending_reviews,approved_plans,by_disease:[{name,count}],by_status:[{name,count}],recent:[...],capabilities:{...}}`。
- GET `/records?q=&status=` -> array `{id,name,type,region,era,status,version,created_at,updated_at,disease_count,image_count,thumbnail_url,is_demo}`。
- POST `/records` `{artifact:{name,type,era,region,location,area_m2,support_type,ground_type,pigment_type},survey:{date,weather,light,equipment,humidity,water_leak},chief_complaint,history,is_demo?}` -> record detail。
- GET `/records/{id}` -> `{id,artifact:{...},survey:{...},chief_complaint,history,diagnosis:{hypothesis,evidence:[],uncertainty},status,version,is_demo,images:[{id,url,width,height,image_type,filename,quality,calibration,created_at}],diseases:[{id,image_id,type,polygon:[[x,y]],area_px,area_cm2,area_ratio,severity,confidence,evidence,field_evidence,confirmed,source,standard_code}],plans:[{id,version,status,record_version,sections:{'3.1':{title,content,citations:[],uncertainty}},citations:[],checks:[],created_at,author,provider,model_version,reviewer,signed_at}],consultations:[...],simulations:[...],audit:[...]}`。
- PUT `/records/{id}` `{expected_version,artifact?,survey?,chief_complaint?,history?,diagnosis?}` -> detail。修改后重新审核。
- POST `/records/{id}/images` multipart `file`, `image_type` (`original`/`followup`/`document`) -> image；GET `/images/{id}/file` 返回受权限保护的方向规范化显示PNG，GET `/images/{id}/original` 下载原始上传字节；原始对象缺失返回409。
- POST `/images/{id}/analyze` -> `{id,status,...}` job；GET `/jobs/{id}` -> `{id,status,result,error}`。结果 predictions 只作为候选，人工保存后写入diseases。无权重说明 unavailable，不自动造病害。
- PUT `/images/{id}/calibration` `{points:[[x,y],[x,y]],length_cm}` -> image。可清除 POST `/images/{id}/calibration/clear`。
- PUT `/records/{id}/diseases` `{expected_version,image_id,items:[{type,polygon:[[x,y]],severity:'轻度'|'中度'|'重度'|'待确认',confidence:null|number,evidence,field_evidence,confirmed,source:'manual'|'model',model_job_id?,proposal_index?}]}` -> detail；替换该图标注，面积服务端算。模型来源须绑定本图已完成任务、候选类型和原多边形；置信度及model_version由服务器任务决定。修改后的多边形须为人工来源，人工来源不保留模型置信度。支持原图坐标多边形，不共用截图坐标。
- GET `/records/{id}/disease-map.svg?image_id=`；`/disease-map.pdf?image_id=` 图示预览导出，含未核验符号标识。
- POST `/records/{id}/extract` `{text,image_id?}` -> `{diagnosis,chief_complaint,history,provider,model_version,uncertainty}`；`image_id`必须属于当前病历，可用于历史档案图像的可选VLM抽取。视觉模型须配置 `AHR_VISION_MODEL`，外发统一要求 `AHR_ALLOW_EXTERNAL_MODELS=true`；图片按服务端限制缩放后发送，未配置/失败返回明确人工回退。文本和模型返回均须经结构校验；结果不自动覆盖病历。
- GET `/knowledge?q=&kind=&disease=&region=` -> `{items:[{id,title,text,source_url,publisher,kind,standard,clause,version,verified,tags,region,material,diseases,outcome}],count}`。
- GET `/records/{id}/similar-cases` -> `{items:[知识条目+score,match_reasons],method}`。公开摘要与完整病例区分。
- POST `/records/{id}/plans` `{use_llm:true}` -> plan；无key有明确template_fallback不冒充LLM。plan包含不可变 `record_snapshot`，审核hash覆盖快照和章节，旧方案PDF使用其生成时快照。
- PUT `/plans/{id}` `{sections,expected_version}` -> 新版本plan，旧版不可覆盖。
- POST `/plans/{id}/check` -> `{plan_id,overall:'pass'|'warn'|'block',items:[{rule_id,name,result,message,basis,basis_status}],rules_version}`。
- POST `/plans/{id}/submit` -> plan，阻断返回409；需当前病历版本且是最新方案。创建新方案或修改病历后，旧待审/已批准方案标为superseded。
- POST `/plans/{id}/review` `{decision:'approved'|'rejected',comment,signature}` -> plan；仅expert、非作者，signature须与当前登录姓名一致；必须是最新方案且处于review状态、重新校验、绑定病历版本与hash。审批文字是内部审核记录，不冒充CA签章。
- GET `/consultations` -> array 待审核方案摘要含record_id,record_name,plan_id,version,status；POST `/records/{id}/consultations` `{comment,plan_id?,decision:'comment'}` -> consultation。
- POST `/records/{id}/simulate` `{image_id,types:[]}` -> `{id,status,...}` job；结果 `{id,url,uncertainty_url,method,watermark,limitations}`；simulation单独存储。
- POST `/records/{id}/compare` `{before_image_id,after_image_id}` -> `{id,status,...}` job；result含comparison_url/metrics/limitations，未配准不可推断真实病害变化。
- GET `/records/{id}/archive.json`、`/archive.pdf`、`/archive.zip`；GET `/plans/{id}/export.pdf`；导出留审计，原始归档不混入模拟图片。
- GET `/audit?record_id=` -> array 审计条目；GET `/system/readiness` -> capability list。

前端：桌面左侧主导航（工作台/病历/循证资料/会诊/审计），记录详情工作区 tabs（影像标注/病历/病例与依据/方案/会诊/模拟对比/档案）。病害颜色由dictionary决定。展示是否演示、来源URL、证据不足、模型状态。所有按钮应接真实API并处理loading/error/空态。示例数据为程序绘制的教学图，不伪装真实壁画。

## xqw-v0增量接口

以下接口继续使用登录身份、机构隔离和已有错误响应；不改变原有病历/方案/档案协议。

| 接口 | 作用与约束 |
| --- | --- |
| `GET /api/v1/reference-images` | 公开参考影像，支持q/region；数量和视图取实际清单 |
| `GET /api/v1/reference-images/{id}/file` | 校验原图哈希后读取馆方JPEG |
| `POST /api/v1/reference-images/{artifact_id}/import` | 按馆藏对象幂等导入；真实照片不产生病害结论或现场调查；保留public_reference身份 |
| `PUT /api/v1/images/{id}/provenance` | expected_version+provenance；更新撤销复核，不允许将已登记合成改称真实 |
| `POST /api/v1/images/{id}/provenance/review` | expected_version、decision、comment；expert/admin独立账号复核 |
| `GET /api/v1/data/readiness` | 本机构实际来源台账、授权状态、图像/对象分项和20份完整病例目标 |
| `POST /api/v1/images/{id}/assist` | expected_version，points/point_labels或box；异步annotation_assistance任务 |

SAM结果从 `GET /api/v1/jobs/{id}` 读取。包含 `image_id`、`source_record_version`、原始/显示图SHA、prompts、model_version、predictions。predictions保留全部连通区域/孔洞和原始掩膜，`confidence`是SAM内部IoU预测，`type=null`。人工采用保存为manual，不能冒充六类监督分割结果；跨影像或旧版本结果不得采用。缺权重返回status=unavailable和空候选，不伪造成功。

病害新增中心线字段的格式以Swagger `/docs` 的 `DiseaseIn` 为准。裂隙中心线与面积多边形分开保存；中心线没有提供时导出待补提示。
