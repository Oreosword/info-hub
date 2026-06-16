# Git 上传前检查

本项目会在本机保存数据库、DeepSeek key、导出日报和旧打包产物。上传 Git 时只提交源码和文档，不提交本机数据。

## 不应提交的内容

`.gitignore` 已排除：

- `infohub.db` 和所有 `*.db` / `*.sqlite*`
- `.env`
- `.venv/`
- `exports/`
- `release/`
- `__pycache__/`
- `.infohub.launch.lock`

## 推荐流程

```bash
git status --short
git add .
git status --short
git commit -m "Release v0.1.1"
```

提交前确认 `git status --short` 里没有：

- `infohub.db`
- `release/`
- `.venv/`
- `exports/`
- `__pycache__/`

## 本地验证

启动服务后运行：

```bash
python -m pytest tests -q
python scripts/smoke_test.py
```

看到 `[smoke] OK` 后再提交。

发布前也请检查：

```text
docs/RELEASE_CHECKLIST.md
```

## 恢复本地数据

如果换机器运行，首次启动会自动创建新的 `infohub.db`。DeepSeek API key 需要在页面的「DeepSeek 设置」里重新保存。
