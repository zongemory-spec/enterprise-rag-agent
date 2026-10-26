# Enterprise RAG Agent

An AI-assisted learning project combining authorized retrieval, tool-calling workflows, persistent checkpoints and evaluation.

当前源码为 v3.4：24 份合成文档，租户/分组/文档权限过滤，引用再次鉴权，SQLite 或 PostgreSQL 状态存储；支持真实语义向量与关键词双路检索、RRF 融合、模型工具规划和请求级 Langfuse 追踪。

## Quick start (offline)

Python 3.12, from the repository root:

```sh
python -m venv .venv
# Activate .venv for your shell.
python -m pip install -r requirements.lock
python run_server.py --port 8006
```

Open http://127.0.0.1:8006. The script generates local synthetic data and credentials in `data/demo_auth.json`. The default SQLite/offline route needs no paid API. Do not commit generated credentials or databases.

## Engineering focus

- Permission checks before retrieval and again before exposing citations.
- Durable workflows: lease, resume, version revalidation and concurrency rejection.
- Optional native model tool planning; bounded request budgets.
- Hybrid retrieval: lexical baseline + semantic pgvector, rank fusion and traceable citations.
- Repeatable tests and synthetic evaluation data under `data/`.

```sh
python -m unittest discover -s tests -v
python evaluate.py --split dev --out reports/local-dev.json
```

Publication check: 66 tests discovered, 59 passed and 7 PostgreSQL-dependent tests skipped in the local offline check. The GitHub workflow separately provisions pgvector; its actual result must be checked in Actions. Historical reports are not rerun results for this publication.

## Optional real-model path and limitations

Read [semantic embeddings](docs/真实Embedding升级与测试.md), [tool planning](docs/真实Agent升级与启动.md), and [hybrid retrieval](docs/混合检索升级与测试.md) before enabling billable calls. Configure your own PostgreSQL and provider credentials. Old machine-specific paths are examples, not prerequisites.

The lexical retriever is not BM25; no reranker is claimed. A small synthetic dataset does not establish production accuracy, enterprise scale or general security. Local demo authentication and request-level tracing are deliberately limited. Real-model tests can cost money and are not run by the default smoke check.

## Versions

Seven local snapshots are available as `snapshot/v1`, `v2`, `v3`, `v3.1`, `v3.2`, `v3.3`, `v3.4` (all use the `snapshot/` prefix). Original per-folder Git records are on `archive/*` branches. [Historical notes](README.legacy.md).

## Development and provenance

This is an educational project developed with AI assistance. See [source history](docs/SOURCE_HISTORY.md) for the original records and local version snapshots. Imported commits are not backdated. Follow [CONTRIBUTING](CONTRIBUTING.md) for future changes.

