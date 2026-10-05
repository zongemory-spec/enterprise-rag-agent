# Enterprise RAG Agent v3

24 份合成文档、权限预过滤、引用再次鉴权、只读工具和持久化任务。SQLite 可独立运行；PostgreSQL 模式保存全部业务状态与向量，不再依赖 SQLite 影子主库。

## 启动

在本目录打开 PowerShell：

```powershell
$env:PIP_CACHE_DIR = 'D:\PythonCache\pip'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\start.ps1
```

访问 http://127.0.0.1:8003 。从本项目 data/demo_auth.json 复制演示凭证。默认不调用外部模型；认证仅用于本机演示。

## PostgreSQL

设置 RAG_STORE=postgresql、RAG_PG_DSN、可选 RAG_PG_SCHEMA 后启动。数据库先安装 pgvector；应用角色应有 CREATE schema 权限，无需超级用户权限。默认启动同步词项哈希向量，是词法基线而非语义模型。

本机可在私密 data/local_config.json 保存：
```json
{"postgres_config":"D:\\PostgreSQL\\config\\connection.json","postgres_schema":"rag_v3","provider_env_file":"D:\\desktop\\Agent Security Mini Lab\\agent_security_real_api_lab_v2_1\\.env"}
```
connection.json 的 dsn 由本机安装时生成。不打包私密配置。源码不会自动启动 Windows 数据库服务。

迁移 SQLite：为目标设置全新空 schema，运行 python migrate_sqlite.py <原SQLite路径>。源库只读打开；文档、版本、撤权、运行记录、工单、审计在单个事务中迁移；非空目标拒绝覆盖。随后运行 python sync_pg.py。

## 复用 Qwen Key

无需把 Key 发到聊天或复制进代码：

```powershell
$env:RAG_PROVIDER_ENV_FILE = 'D:\desktop\Agent Security Mini Lab\agent_security_real_api_lab_v2_1\.env'
.\.venv\Scripts\python.exe sync_pg.py --real
.\start.ps1 -Real
```

真实向量路径先配置 PostgreSQL。以上命令会产生费用。读取原文件 DASHSCOPE_API_KEY、QWEN_BASE_URL、QWEN_MODEL；embedding 默认为 text-embedding-v4、1024 维、每批最多 10 段，地域与工作空间权限须匹配。日常服务调用不受本轮独立验收脚本的 20/5 次额度约束。

## 持久化任务

POST /agent 可提交 workflow_id，最多 64 个字母、数字、下划线或横线。同一身份、ID、问题和方法恢复同一任务；不提供 ID 时新建。为避免响应丢失后无法恢复，客户端应从首次请求起指定 ID。

默认文件为 data/checkpoints.sqlite3；PG 模式使用 workflow_checkpoints 表。每步只读工具完成后保存；进程崩溃后等待最长 300 秒租约到期，再用相同 ID 重试。并发返回 409；恢复重验权限和知识版本，版本改变时拒绝旧任务。

检查点保存工具调用和结果，可能包含问句与引用，属于私密运行数据。没有实现加密、自动保留期或 LangGraph Saver 接口。最后一步保存前崩溃可能重跑并再次产生费用，不承诺付费调用恰好一次。普通 runs 表仍只保存元数据。

## Langfuse

已实现 HTTP ingestion 适配器并接入 API 请求审计，不是 Noop 占位。默认关闭。设置 RAG_TRACING=langfuse，以及 LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY 后启用。

仅发送路由模板、耗时和状态码，不发送问题、资料或身份。失败不阻断业务；app.state.tracer.last_status 可检查最近状态。已验证本地 HTTP 接收器、部分拒收和网络异常；没有真实后端凭据，不能声称控制台已验收。仅请求级追踪，未实现模型逐 span 追踪或持久化发送队列。

## Docker

compose.yaml 包含 PG/pgvector 与 RAG，数据使用命名卷，应用端口仅绑定本机 8003。先设置非空 RAG_DB_PASSWORD，再运行 docker compose up --build。容器数据库用户仅作本地合成演示。

已修复启动文件与 .dockerignore 不匹配。**Docker Desktop 尚未安装，镜像没有实际构建或运行。** 上次检测固件虚拟化未开启；须在具备系统权限时完成安装与环境准备，不能把配置交付当作容器验收。

## 验证与边界

54 项测试全部通过，含 PostgreSQL 17.11 / pgvector 0.8.6、迁移、事务回滚、跨进程恢复和权限重验。数据库验证使用工作区临时合成测试库和非超级用户应用角色，不代表 D 盘部署或 Docker 已验证。

运行 python -m unittest discover -s tests -v；未设置 RAG_TEST_PG_DSN 时六项 PG 测试跳过。测试使用唯一 schema，保留供检查。

reports/dev-v2、test 是历史关键词/词项哈希评测，不能当作本轮真实语义模型结果。真人讲解、人工相关性评审、远端 CI、生产上线仍未完成。python package_source.py 导出源码白名单，不含私密配置、密钥、数据库和虚拟环境。
