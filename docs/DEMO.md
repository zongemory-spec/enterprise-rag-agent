# Reproducible RAG walkthrough

[README](../README.md) · [Design and limitations](DESIGN.md)

This walkthrough uses only the repository's synthetic documents and local demo identities. Complete the README's offline setup first and open http://127.0.0.1:8006. Keep `--real` and `--semantic` disabled for this walkthrough.

## 1. Ask a question and inspect the evidence

1. Open the generated `data/demo_auth.json` locally. Find `user_id: alice`, `tenant_id: demo`; copy only that record's token into **访问凭证**. Do not post the file or include its token in screenshots.
2. Leave retrieval set to **关键词基线** and ask `差旅报销和入职材料分别有什么要求？`.
3. Click **查阅资料**. Inspect the answer and source buttons; open a source to see the quoted text.

Expected behavior: answers use currently authorized evidence or refuse when it is insufficient. Source links are server endpoints that check access again; a returned source ID is not a permanent access grant.

## 2. Compare two identities

Repeat the same question with `bob` in tenant `demo`, using Bob's local token. Alice belongs to `support`; Bob belongs to `engineering`. Accessible documents and results can differ. Public documents may be shared, so not every question produces a different answer.

For an explicit identity boundary, use **查询我的工单 T1001**:

| Identity | Synthetic record | Expected behavior |
| :--- | :--- | :--- |
| Alice, tenant `demo` | T1001 belongs to Alice | The workflow can return Alice's own ticket. |
| Bob, tenant `demo` | Same T1001 | Access is denied. |
| Alice, tenant `other` | Same T1001 | Access is denied across tenants. |

These are controlled demo identities, not a production authentication system. The regression suite additionally checks citation authorization, document updates and checkpoint recovery.

## 3. Compare retrieval and workflow modes

- **词项向量对照（离线）** uses a lexical hash-vector baseline. It is not a pretrained semantic model.
- **让 Agent 完成问题** uses the offline scripted route by default. The page labels it as such; this does not demonstrate autonomous model planning.
- **混合检索 / 数据库向量检索** require a configured database index. On an untouched offline setup, an unconfigured-index error is expected. Do not enable paid services just to make this demo button succeed.

For recovery, concurrency, revocation and real-adapter scenarios, run the repository tests and follow the linked mode guides. Avoid treating a successful single browser interaction as proof of all these cases.

## Read the evaluation report

```sh
python evaluate.py --split dev --out reports/my-dev.json
```

Use a filename that does not already exist. Two files are generated:

| File | Contents |
| :--- | :--- |
| `my-dev.md` | A compact comparison of offline methods and questions requiring analysis. |
| `my-dev.json` | Dataset version / SHA-256, metrics and per-question answers, citations and failure details. |

Read Recall@4 together with correct refusal, false refusal, reference-point coverage and leak-event counts. Exact-quote support is only a substring check. Zero leaks in a small synthetic set do not imply zero risk elsewhere.

This command evaluates `keyword` and `hash-vector`; it does not call paid models or measure semantic / pgvector quality. The final `test` split requires explicit `--allow-test`; keep it separate from routine dev tuning.

## Download the current CI evidence

1. Open the repository's **Actions** tab and choose **offline-and-pgvector**.
2. Select the run for the commit you want to inspect, and check its conclusion.
3. Read the job summary, then open **Artifacts → offline-dev-evaluation-<commit SHA>**. GitHub may ask you to sign in before downloading.
4. Download the archive containing `ci-dev.json` and `ci-dev.md`. The artifact expires after 14 days.

Artifacts contain only the evaluator's synthetic report files. Credentials, databases and private configuration are not included. If tests or evaluation failed before report creation, there may be no report to download; consult the failing step rather than an older artifact.
