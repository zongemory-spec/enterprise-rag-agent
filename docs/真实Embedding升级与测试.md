# v3.3 真实 Embedding 升级与测试

同级新目录，不修改 v3.2。Git 修改前标签 baseline-v3.2，提交 0b04064。私有配置、凭证和预算数据库均不进入 Git/源码压缩包。PostgreSQL 独立 schema 为 rag_v3_3_semantic。

## 新增能力

1. `--semantic` / `-Semantic` 显式启用真实 text-embedding-v4（1024维）查询；与真实对话模型开关独立。
2. 原文片段经真实 Embedding 编码后写入 pgvector，问题用相同配置编码，SQL 中执行租户与文档权限过滤后排序，取回授权原文。
3. 模型标识包含模型名、维度和服务地址指纹；不会把不同向量空间混在一起查询。当前实现没有模型权重版本校验，服务端模型更新仍需主动重建和评测。
4. 查询前检查索引是否完整且属于当前知识版本。缺失、模型切换或资料变更时返回409，要求显式重建；不悄悄退回哈希检索，不自动产生大批建库费用。
5. 建库脚本发现当前索引已就绪就跳过，避免启动反复调用Embedding。
6. 本地SQLite预算计数跨脚本与服务重启保留，失败请求也计数。当前限额Embedding12次、chat4次，只控制请求数量，不是精确费用限额，也不是不可篡改账单系统。
7. 网页显示真实语义/词项哈希、模型标识、索引状态及已用预算；真实语义模式自动选择pgvector检索。

Embedding接口接收文本并返回向量，不是对话LLM根据prompt编写一串数字。pgvector只保存和比较向量；存哈希向量时它不会自动获得语义能力。参考[服务商Embedding接口说明](https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api)。

## 本次实际验收

- 24个合成片段真实编码并存入pgvector，索引全部就绪。
- 62项回归通过，包含PG、权限撤销、向量空间不匹配、索引过期及持久化预算。
- 4条人工挑选的改写问题：关键词Hit@4为0/4，语义检索为3/4。仅说明这组样例的区别，不是通用准确率或无偏性能基准。
- “出差花的钱怎样拿回来”中目标文档在第2位，第一位为退款文档，说明语义检索仍会带入不适用候选。
- 第4题“上线之前哪些事项要确认”未命中预设E001；E001实际仅规定发布窗口，问题与目标标注本身也存在歧义。该失败记录保留，不把这项结果当成可靠质量分数。后续应先清理标注，再做更大独立评测集。
- 真实Agent使用pgvector完成T1001查询→知识检索→综合回答，open及500元引用正确。Bob查Alice工单被拒绝，Alice检索结果未出现其他租户/工程私有文档。
- 实际消耗8次Embedding（建库3次、改写查询4次、Agent检索1次）和4次对话请求，没有充值。

详情：reports/semantic-v3.3.json。旧reports和旧说明保留作历史记录，不能当作本版本Docker验收。本次未构建新Docker镜像。

## 本地启动与测试

在本v3.3目录打开PowerShell。start.ps1优先使用本目录虚拟环境，缺失时复用同级v3.1的已安装Python，不修改其文件。

当前已建好真实索引。先只测试语义检索，不产生新对话费用：

```powershell
.\start.ps1 -Semantic
```

打开 http://127.0.0.1:8005 ，使用本目录 data/demo_auth.json 中 demo租户Alice的token。页面应显示真实语义Embedding、text-embedding-v4、索引就绪。输入“买错了能退钱吗？”，选择数据库向量检索，点击“查阅资料”。这里答案生成仍为本地原文抽取，检索是真实Embedding；不是完整真实Agent。

剩余Embedding预算4次。每次发送pgvector问题通常消耗1次；点击引用、健康检查和查看模式不消耗Embedding。可切换关键词进行无额外API费用的对照。不要为了重复演示删除预算数据库。

完整真实Agent启动方式是 `.\start.ps1 -Real -Semantic`，但本次chat4次验证限额已用完，继续点击真实Agent会被预算拒绝。预算不应为绕过限额而自动重置；需确认可用对话额度后再调整并继续。本次已经有真实联动验收结果，无需重复支付才能证明实现。

资料修改后，需要显式运行 `.\start.ps1 -Semantic -BuildIndex` 重建。全量24片段需3次Embedding，当前仅余4次，不要在资料未变更时重建。重复执行当前就绪索引的建库脚本会跳过。

Git比较：`git diff baseline-v3.2 HEAD`。要查看基线，确保工作区干净后用 `git switch -c inspect-baseline baseline-v3.2`；返回 `git switch main`。源码切换不会恢复PG数据/预算。本次源码包位于dist/enterprise-rag-v3_3.zip。

## 能体现的岗位能力

真实模型API集成、语义检索与pgvector、模型/索引生命周期、权限预过滤、Agent与检索联调、成本预算、基线对照和失败分析。仍没有实现LoRA训练、LangGraph或生产容量验证。
