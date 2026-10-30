# v4.0 升级说明

本次基于 SOURCE_BASELINE.json 中的上游提交实现，完整保留合成数据、旧测试和历史说明。

## 实现变化

- LangChain：实际使用 BaseRetriever / Document / StructuredTool；可选 ChatOpenAI 规划器会调用 bind_tools。
- LangGraph：/agent 已改为 StateGraph 节点执行，沿用原有按身份隔离的应用层检查点。原 Service.agent 兼容入口仍保留，HTTP /agent 使用新的图流程。
- BM25：Okapi BM25，k1=1.5、b=0.75；jieba 分词与中文二元词项，语料统计来自当前可访问片段。未沿用原向量的 0.15 阈值。
- 混合：hybrid 使用 BM25 + pgvector；hybrid-local 明确使用 BM25 + 哈希词项向量。RRF constant=60。
- 重排：候选数扩大为 max(20, top_k*4)，本地 CrossEncoder 或 HTTP 适配器重排后截断；默认关闭，显式请求才调用。
- 观测：Langfuse OTLP 父子 span，记录阶段和可用的 token 统计；不上传原文或问题。
- 评测：新增 Recall@1、Hit@1、MRR@4，保留 Recall@4，保留返回次序，支持重排前后对照和显式真实运行库评测。
- 交付：基础依赖锁文件、可选 ML 依赖、配置示例、前端入口和带 SHA-256 文件清单的源码打包脚本。

## 保留的边界

模型、文档和工具结果不能改变服务器身份或授权范围。所有新检索路径沿用预过滤，融合和重排候选重新授权；引用生成后和打开时继续复查。LangGraph 的应用层恢复需要重新检查版本及权限。

没有新增生产 SSO、大规模倒排索引、pgvector ANN 索引、LangGraph 原生 Saver、Langfuse 可靠发送队列或服务商价格计算。检查点与预算数据库应由本机权限保护。基础测试不需要真实模型；使用模拟响应验证协议不等于测试了模型效果。

## 评测解读

报告以当前固定 dev split 为准。新增组件不会自动改善所有题目；BM25 的任意词项命中可能召回弱相关内容，仍需在更大标注集上调节召回和拒答策略。重排序可重新排列已召回内容，不能凭空补回候选集缺失的文档。不要根据这些合成样本编造真实语义或生产准确率。

test split 未参与本次调参和报告。历史 reports 下的 v3.x 文件保留作来源记录；本次结果以 v4-* 文件为准。
