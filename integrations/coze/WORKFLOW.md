# Coze / 扣子接入与示例工作流

1. 将本后端部署到平台可以访问的 HTTPS 地址。云端扣子不能访问本机 127.0.0.1；中国区与国际区使用对应的平台账号和服务地址。
2. 运行 `python export_integrations.py --base-url https://你的服务域名`，使用生成的 coze/openapi.json 或 openapi.yaml 创建基于已有服务的插件。
3. 配置 Authorization: Bearer 平台凭证。该凭证由本后端 init_platform_auth.py 生成，不是你的 Coze Access Token；两者用途不同。
4. 在平台内调试、发布插件，再添加到智能体或工作流。

提供的工具：

|工具|用途|
|---|---|
|cozeAskKnowledge|调用证据检查后的完整问答；支持 conversation_id 多轮追问|
|cozeSearchKnowledge|只返回已授权、经过证据筛选的片段；不调用回答生成器|

建议第一个工作流按“开始(query, 可选conversation_id) → 插件cozeAskKnowledge → 结束(answer, citations, refused, conversation_id)”搭建。无证据时原样返回拒答，不根据常识补写企业政策。跨轮 conversation_id 由可信应用端或会话变量维护。

多用户场景使用 delegated 身份模式，由可信调用端额外注入 X-RAG-User-Token。普通插件的固定服务密钥不会自动对应最终用户；不要让模型传入 user_id / tenant_id / groups 来决定资料访问范围。service 模式仅适合固定身份可共享的资料范围。

这份源码提供后端、协议文件和节点搭建说明，未在用户账号中实际导入或发布。工作流跨空间复制时，平台插件资源需要按目标空间重新绑定，不能把后端 ZIP 当成平台原生工作流导出包。

真实联调可发布同步工作流，然后配置 COZE_API_BASE_URL（例如 https://api.coze.cn）、COZE_API_TOKEN、COZE_WORKFLOW_ID 和 COZE_VERIFY_PARAMETERS：

```sh
python verify_services.py --env-file .env --services coze --allow-external --strict --out reports/coze-live.json
```

脚本调用 /v1/workflow/run 并检查成功码和同步结果。需要异步/流式节点的工作流不属于该同步探测脚本的验证范围。

依据：[导入插件](https://www.coze.com/open/docs/guides/plugin_import)、[执行工作流](https://docs.coze.cn/developer_guides_workflow_run)。
