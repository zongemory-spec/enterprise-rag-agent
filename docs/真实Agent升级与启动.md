# v3.2：真实模型 Agent 升级与启动

原 v3.1 保留不变。本目录是同级新版本，先以 Git 提交并标记 baseline-v3.1，再修改代码。原 Lab 的 Qwen 路径不需要因此删除或重写；之前离线演示的展示没有充分区分真实模型与脚本，是交付说明的不足。

## 这次新增什么

- Qwen 原生 Function Calling：提供 search_knowledge / get_ticket_status 两个只读工具，模型逐步选择工具及参数，后端执行并把工具结果回填。
- 多步综合回答：工具检索先在本地抽取可核对的原文，最后由模型综合工单状态与政策；每条回答必须关联存在的证据编号，知识引用可点击查看原文。
- 权限仍由后端决定：检索前过滤，工单对象鉴权，模型调用后及检查点恢复时重新检查引用权限和知识版本。
- 网页明确区分真实模型与离线单步脚本；新增“让 Agent 完成问题”按钮，原“查阅资料”按钮保留为检索对照。
- 检查点保存工具执行结果、综合回答及模型尝试次数。完成的同一工作流恢复时不会重复调用模型。
- 每任务最多 3 次工具执行、5 次模型尝试；60 秒期限在阶段边界检查，模型请求分别有 15/20 秒网络超时。同步工具不能被此期限强制中断。
- 服务进程默认最多 9 次真实 Agent 对话尝试（本次验证后原授权剩余额度），失败也计数。此计数重启会重置，不是跨进程或每日账单限制；授权余额仍需人工累计。

真实聊天与 embedding 分开配置。默认关键词检索不调用 embedding。/ask 若人为另外启用 RAG_GENERATOR=real，属于独立旧路径，其模型调用不纳入新 Agent 的进程计数，不要在本次剩余额度验证中启用。

## 如何启动

在此目录打开 PowerShell。新目录没有复制虚拟环境，start.ps1 会优先使用本目录环境，缺失时复用同级 v3.1 已安装的 Python 环境，不修改它。

离线：

```powershell
.\start.ps1
```

真实 Qwen（密钥通过原 Lab 文件引用，不复制或打印）：

```powershell
.\start.ps1 -Real -ProviderEnvFile 'D:\desktop\Agent Security Mini Lab\agent_security_real_api_lab_v2_1\.env'
```

打开 http://127.0.0.1:8004 。初始化会在**本 v3.2 目录**生成 data/demo_auth.json。完整凭证路径为：

`D:\desktop\Enterprise RAG Agent\Enterprise RAG Agent v3_2\data\demo_auth.json`

这个凭证属于 v3.2 本地环境，不能默认与旧 Docker 或 v3.1 凭证共用。启动后应显示“真实模型 Agent”，否则不要把离线结果当成模型规划。

用 Alice 凭证、关键词检索，输入：

> 查询我的工单 T1001 的当前状态，并查询退款审批条件，分别说明结果。不要猜测工单内容。

点击“让 Agent 完成问题”。应显示 get_ticket_status → search_knowledge（顺序可不同），回答工单 open 和退款上限 500 元，并能打开引用。切换 Bob 查询 T1001 应被拒绝。工单合成数据只有状态，不包含问题内容，不能声称模型识别了工单主题。

## 测试与复原

自动回归沿用 README 命令，新增 tests/test_agent_upgrade.py 覆盖原生工具协议、多步综合、伪造引用、调用预算、恢复不重复调用和生成期间权限撤销。verify_real_agent.py 会产生付费请求，只应在新的明确额度内运行；它内部最多 6 次对话请求、零 embedding。

Git 查看版本：`git log --oneline`；比较升级：`git diff baseline-v3.1 HEAD`。

如需查看并运行修改前代码，先确保 git status 干净，然后 `git switch -c inspect-baseline baseline-v3.1`。返回升级版用 `git switch main`。切换源码不会复原运行数据，data 下数据库和凭证不在 Git 中；原 v3.1 本身仍可直接启动。

## 能力与边界

现在能够演示：原生工具调用、模型驱动的多步编排、检索增强回答、来源追溯、对象与租户鉴权、SQLite/PG 检查点恢复、回归测试及真实服务验收。适合对应 AI/Agent 实习 JD 的工具集成、后端接口、RAG、调试与工程验证要求。

本实现是自建 Agent 循环，**不是 LangGraph，也没有 LoRA 微调**。引用 ID 与原文权限能被程序检查；综合文字是否正确理解原文，仍需要语义评测，不能把存在引用等同于答案完全正确。Langfuse 保留原请求级观测，不因此声称已有完整模型步骤追踪。未加入分布式限流、生产并发容量验证或企业生产部署。本次未替换旧 Docker 服务；旧镜像不会自动包含 v3.2 代码。

旧 README、历史报告描述的是 v3.1 基线；本说明和 reports/real-agent-v3.2.json 描述新增能力。本次真实测试是一条合成复合任务，不是覆盖所有需求的性能基准。
