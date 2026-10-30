# v4.0 验证记录（2026-10-29）

## 自动测试

Python 3.12.10，Windows，本地独立虚拟环境。运行 `python -m unittest discover -s tests -v`：

- 90 项测试，83 项通过，7 项跳过，0 项失败。
- 跳过的 7 项均需要 `RAG_TEST_PG_DSN`：本机没有配置 PostgreSQL / pgvector 测试服务。
- 覆盖中文 BM25、词频排序、LangChain 检索与工具 schema、LangGraph 失败恢复、检索前权限过滤、重排前候选隔离、重排过程中撤权、伪造候选拒绝、API top_k / rerank 传递、预算、排序指标、Langfuse 父子 span 与元数据脱敏，以及 ZIP 清单和排除规则。
- `python -m pip check` 通过；基础依赖版本记录在 requirements.lock。
- Python 源码编译检查通过。

## 固定 dev split 实测

运行 `python evaluate.py --split dev --out reports/v4-dev.json`；未访问最终 test split，未调用外部模型。

|方法|题数|Recall@1|Hit@1|Recall@4|MRR@4|正确拒答|
|---|---:|---:|---:|---:|---:|---:|
|keyword|30|0.875|1.000|1.000|1.000|1.000|
|hash-vector|30|0.725|0.800|0.725|0.800|1.000|
|bm25|30|0.875|1.000|1.000|1.000|0.900|
|hybrid-local|30|0.850|0.950|1.000|0.975|0.900|

原始问题和逐题结果、召回顺序、拒答情况、引用检查与耗时见 v4-dev.json。hybrid-local 的向量部分是词项哈希，不是预训练语义 Embedding。

这些数据没有证明混合检索一定更好。BM25 / hybrid-local 对 dev 中 Q047 发生弱相关召回，降低了正确拒答；需要结合更大标注集和真实重排器进一步分析，而不是根据是否召回内容直接认定可回答。

## 验证边界

- 未运行真实 PostgreSQL / pgvector 服务，未实测真实 Embedding 质量；保留原集成测试及 CI 数据库验证配置。
- HTTP 重排、LangChain 模型返回、CrossEncoder 分数使用受控响应或测试替身验证协议和衔接；本机未下载神经模型权重，也未验证其排名质量或性能。可选 requirements-ml.txt 不属于本次已安装的基础环境。
- Langfuse 已验证 OTLP 请求、父子关系、阶段记录、失败隔离和不输出原文；未连接用户的真实 Langfuse 项目。
- 不包含真实模型效果提升、生产容量、生产权限配置或成本统计的承诺。

## 交付检查

源码打包包含文件 SHA-256 清单；排除 .git、.venv、密钥、.env、运行数据库、生成的身份凭证和模型权重。解压启动检查结果见本记录末尾。

解压验证已完成：对候选源码 ZIP 中的 111 个文件逐一校验 SHA-256，全部一致；从新解压目录使用基础测试环境启动 `run_server.py --env-file .env.example` 成功。网页、health、capabilities、401 鉴权、BM25 问答、引用打开、LangGraph hybrid-local、top_k 传递及未配置重排时的 503 响应均通过。验证时生成的凭证和数据库仅存在于测试解压目录，没有回填到源码包。最终交付使用同一源码，仅补入本段验证记录后重新生成清单。
