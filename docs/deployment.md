# 环境、运行和部署

## 本地运行

`python3 run.py` 自动使用项目内Conda环境，在127.0.0.1:8765启动FastAPI并提供已构建的React页面。开发模式的本地数据库和文件均在 `runtime/`。每次启动只在空库初始化，不清空已有病历。修改前端后运行 `python3 run.py build` 并刷新页面。

`python3 run.py setup --with-ai` 管理项目环境；基础版本在requirements.txt，当前已测Conda与pip快照在 `deploy/environment-explicit-linux-64.txt` 和 `deploy/requirements-tested-lock.txt`。平台快照仅用于Linux x86_64复现，CPU torch使用PyTorch官方CPU索引；其它系统按environment.yml重建。GPU版本请在独立Conda环境匹配CUDA驱动，不把CPU轮子当作GPU支持。

项目 `.env` 由pydantic-settings读取，系统环境变量优先；修改配置后重启。未配置外部服务可运行本地流程。MaaS、视觉及embedding外发都需要明确的 `AHR_ALLOW_EXTERNAL_MODELS=true`。不要把密钥放进截图、Git或交付包。

## PostgreSQL、Redis与华为OBS

| 服务 | 配置 | 实际用途 |
| --- | --- | --- |
| PostgreSQL/RDS | `AHR_DATABASE_URL=postgresql+psycopg://...` | 全部业务表；事务、病历版本锁及方案唯一版本；RDS连接可附 `?sslmode=require` |
| Redis | `AHR_REDIS_URL=redis://...` 或 `rediss://...` | 相似案例检索缓存，TTL900秒；断连回退直接查询，不承担任务持久队列 |
| OBS | `AHR_STORAGE=obs` 及OBS endpoint/bucket/AK/SK | 原图、规范化影像及模拟文件；官方SDK `esdk-obs-python`，HTTPS校验，私有ACL |
| MaaS兼容服务 | LLM、VISION、EMBEDDING配置 | 草案、文本/图像抽取和可选向量重排 |

OBS上传成功后写入本地缓存，下载采用临时文件及原子替换；非2xx响应不算成功，404视为文件缺失。文件未包含数据库事务，失败时可能留下无数据库引用的对象，需要依据记录索引清理，不能按“未访问”直接删原始资料。应用不返回公开桶链接，所有图像经过机构与身份鉴权。

这些适配器已实现；本次没有RDS/OBS/MaaS资源或凭据，未完成真实云端联调。当前没有把SQLite测试称为PostgreSQL并发压测。所有写业务记录的路径采用Record→Plan一致锁顺序，并以版本冲突返回409；正式上线仍须测试目标数据库的并发和备份恢复。

## 容器部署准备

仓库提供Dockerfile、`deploy/compose.yml`、HTTPS反向代理示例。镜像内通过Conda安装Python和Node并构建前端。默认容器只包含基础依赖，以人工标注为起点；运行学习模型需在镜像中安装AI依赖并挂载经过审核的权重。

先复制 `.env.example` 为 `.env`，填入独立强密码 `AHR_BOOTSTRAP_PASSWORD`（至少12字符）、`POSTGRES_PASSWORD`、`REDIS_PASSWORD`。数据库密码建议用URL安全字符，复杂字符应正确URL编码。然后：

```text
python3 deploy.py plan
python3 deploy.py up
python3 deploy.py status
```

这会在已有Docker主机启动应用、PostgreSQL16、Redis7，应用只绑定127.0.0.1:8765。不会购买云资源。停止容器：`python3 deploy.py down`，默认保留数据卷。**容器启动尚未在本轮实际运行，需目标主机验收。**

生产模式设置 `AHR_ENV=production`、`AHR_DEMO_MODE=false`、唯一管理员密码和实际站点的 `AHR_ALLOWED_ORIGINS`。production要求浏览器通过HTTPS访问，否则Secure cookie不会生效。可参考 `deploy/nginx.conf.example`，替换域名和证书路径。已有演示库不会因为修改配置自动清空；生产请使用独立空数据库和文件存储。初始非演示环境仅生成admin，管理员登录Swagger的 `/api/v1/users` 创建本机构成员；不提供后台自动伪造专家资格。

## 任务、备份与运行边界

当前任务状态持久化在数据库，执行器是单进程FastAPI BackgroundTasks；服务重启会把未完成任务标记为失败，用户可重新提交。适合本地演示和小规模试用。不要以多worker直接部署这一执行器，否则启动恢复逻辑可能干扰其它worker；生产并发应先接入持久工作队列、锁及幂等处理，再做相应验收。

当前启动会执行backend/ahr/migrations.py中的幂等增量迁移，保留既有病历、方案、影像；新增来源和中心线等字段。PostgreSQL使用事务级迁移锁。后续升级需继续编写与验证迁移，不能用删除数据库代替升级。SQLite备份须停止服务或使用SQLite备份接口，同时保存runtime/files；PostgreSQL应做逻辑备份并同步OBS对象版本和对象清单。恢复后逐项验证原图SHA、方案引用、版本与文件下载。

审计保留操作者、前后值、版本及哈希链接。它用于追溯，并非外部不可篡改存证或CA签章；高并发无记录对象的日志可能形成分支，不能把链式字段称作司法级证据。访问控制按机构隔离，当前无公网注册、MFA、遗忘密码服务；需要这些能力时在上线前接入机构认证并完成验收。

## 发布包

```text
python3 deploy.py package
```

输出 `runtime/releases/artifact-health-record-v1.0.tar.gz` 及SHA-256清单，包含源代码、构建产物和知识摘要，排除 `.env`、runtime业务记录、Conda、node_modules、模型权重和原始训练数据。打包不是部署；接手主机仍需安装环境和真实服务配置。

## xqw-v0补充

`python3 run.py setup --with-ai`现在读取完整requirements-ai.txt；`python3 run.py script fetch_models.py --models dinov2 sam resnet34`自动在项目解释器执行下载工具，无需先激活shell。配置AHR_SAM_MODEL_DIR/AHR_RETRIEVAL_MODEL_DIR后再启动；容器内路径需指向实际挂载权重。基础Docker镜像未安装完整AI依赖，需另行构建含AI依赖的镜像，并为模型目录配置只读挂载；本轮未声称容器模型链路已经跑通。

发布包只包含明确的工程目录、data/knowledge、data/rules、data/templates和data/public；runtime与未审核研究数据、模型、.env和密钥被排除，拒绝符号链接。公开馆藏样例与许可元数据一同分发。`python3 run.py verify`验证可携带数据包；它不连接云服务。
