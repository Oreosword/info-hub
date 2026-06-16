# 发布检查清单

发布前按顺序检查，避免把本机数据或不稳定版本推到 GitHub。

## 版本信息

- 更新 `src/app_info.py` 的版本号。
- 更新 `CHANGELOG.md`。
- 确认 README 中的版本号与本次发布一致。

## 本地验证

```bash
python -m py_compile start.py src/app_info.py src/config.py src/core_logic.py src/database.py src/deepseek_client.py src/ai_workflow.py src/workflow.py src/daily_renderer.py src/scheduler.py src/main.py src/routers/api.py src/routers/serializers.py src/routers/sse.py src/fetchers/rss.py src/fetchers/github.py src/fetchers/hackernews.py src/fetchers/arxiv.py src/fetchers/summarizer.py scripts/smoke_test.py
python -m pytest tests -q
```

启动服务后再运行：

```bash
python scripts/smoke_test.py
```

## 数据安全

确认 `git status --short` 中没有这些内容：

- `infohub.db`
- `.env`
- `.venv/`
- `exports/`
- `release/`
- `__pycache__/`
- `.infohub.launch.lock`

## GitHub

- CI 通过。
- tag 名称使用 `vX.Y.Z`。
- Release 说明包含主要变更、验证结果和已知限制。
