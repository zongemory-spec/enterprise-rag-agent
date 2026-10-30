# Dify 接入与示例工作流

## 完整问答工具（建议先使用）

1. 将本后端部署到 Dify 服务器能够访问的地址。Dify Cloud 不能直接访问你的 127.0.0.1；自部署 Dify 要使用容器能访问的后端地址，并按部署网络策略配置访问范围。
2. 运行 `python export_integrations.py --base-url https://你的服务域名`，重新生成 openapi.json / openapi.yaml。仓库自带的 example.invalid 地址只是占位符。
3. 在 Dify 的工具管理入口导入 OpenAPI 文件，按平台界面配置 Bearer 平台凭证。凭证来自本服务私有的 data/platform_auth.json，不是 Dify 应用 API Key。
4. 创建工作流：用户输入(query) → 工具(difyAskKnowledge) → 输出(answer, citations, refused, conversation_id)。需要更稳定的字段控制时，可用 HTTP Request 节点直接 POST /integrations/dify/ask。
5. 首轮省略 conversation_id；后续请求由应用会话变量或可信调用端保存并传回同一 ID。工具参数不能增加 actor、groups、tenant_id。

示例请求：

```json
{"query":"差旅报销的规定是什么？","method":"bm25","top_k":4,"rerank":false}
```

后续请求：将上次返回的 conversation_id 与新问题“那期限是几天？”一起发送。保留后端的拒答文字和引用；不应再要求另一个模型扩写成缺少证据的确定性答案。

本包提供 API、OpenAPI 描述及人工配置步骤，没有伪造平台导出的 DSL 文件。平台界面及导入结果需要在你的实际 Dify 版本中验证。

## 外部知识库

- 外部知识 API endpoint 填 `https://你的服务域名/integrations/dify`，Dify 会追加 `/retrieval`。
- 配置允许的 knowledge_id，例如 enterprise；API Key 对应 mode=service 的平台身份，或通过可信网关注入用户令牌的 delegated 模式。
- 当前 knowledge_id 是允许的知识源别名校验，不代表已经隔离多个独立语料库；实际访问边界由身份和数据库权限控制。
- 请求包含 knowledge_id、query、retrieval_setting.top_k、score_threshold。
- 返回 records 的 content、title、score、metadata。score 是本项目的词项覆盖率（0～1），不是经过校准的语义相关概率；阈值建议先用 0，再依据自己的标注集调节。
- `RAG_PLATFORM_METHOD` 控制检索方法，默认 bm25；`RAG_PLATFORM_RERANK=on` 显式启用已配置的重排器。
- 目前不支持 metadata_condition；非空过滤条件会返回 422，避免静默忽略。
- 外部知识库模式只返回已筛选片段，不调用本项目生成器。最终答案由 Dify 生成，后端无法验证平台随后新增的文字。

## 身份模式

service：所有该工具的调用使用固定服务身份，适用于明确授权共享的资料范围；不能自动识别 Dify 最终用户。

delegated：除平台 Bearer 凭证，还必须有 `X-RAG-User-Token`（本后端真实用户凭证）。需要由可信 HTTP 节点或网关注入；禁止让模型填写这个值。后端检查同租户，并将用户分组与平台允许分组取交集。Dify 原生外部知识库协议没有默认提供最终用户令牌，不能据此宣称已经实现用户级单点登录。

## 真实验证

发布一个调用本后端的 Dify Workflow，配置 DIFY_API_BASE_URL（通常以 /v1 结尾）、DIFY_API_KEY 和 DIFY_VERIFY_INPUTS，运行：

```sh
python verify_services.py --env-file .env --services dify --allow-external --strict --out reports/dify-live.json
```

脚本检查工作流运行状态，不会自动创建或发布你的平台应用。未提供配置会标记 not_configured，严格模式返回非零状态。

协议依据：[Dify 工具](https://docs.dify.ai/en/cloud/use-dify/workspace/tools)、[外部知识 API](https://docs.dify.ai/en/cloud/use-dify/knowledge/external-knowledge-api)、[HTTP Request 节点](https://docs.dify.ai/en/cloud/use-dify/nodes/http-request)。
