# AI 日报生产台

[![CI](https://github.com/Oreosword/info-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/Oreosword/info-hub/actions/workflows/ci.yml)

版本：`0.1.1`

本项目是本机运行的 AI 资讯日报生产系统，提供「信息采集 -> 候选池 -> AI 初筛 -> 人工复核 -> 日报导出」闭环，用于制作 AI 资讯日报。

## 快速开始

### 推荐方式：桌面双击打开

1. 双击桌面快捷方式：`AI 日报生产台.lnk`
2. 系统会自动启动本地服务。
3. 浏览器会打开：`http://127.0.0.1:8000/`

如果桌面快捷方式丢失，也可以进入项目根目录，双击：

```text
打开 AI 日报生产台.cmd
```

启动器会先检查服务是否已经运行：

- 已运行：直接打开浏览器页面。
- 未运行：使用 `.venv` 中的 Python 启动源码服务。
- 8000 端口被其他程序占用：显示明确错误提示。

## 日报生产流程

1. 信息采集：抓取 RSS / GitHub / Hacker News / arXiv，也支持手动导入。
2. 简介中文化：DeepSeek 或规则模式把英文 description / abstract 压缩成简体中文简介。
3. 初筛聚合：生成摘要、关键词、栏目、评分、风险提示，并合并相似事件。
4. 人工复核：在「筛选台」标记候选、入选或忽略，并修正标题、栏目、草稿。
5. 日报生成：在「日报生成」导出 `daily.md`、`daily.html` 和 `assets.json`。

## DeepSeek API

在页面的「DeepSeek 设置」中配置：

- `API key`：明文保存在本机 SQLite。
- `Base URL`：默认 `https://api.deepseek.com`。
- `分析模型`：默认 `deepseek-v4-flash`。
- `成稿模型`：默认 `deepseek-v4-pro`。

未配置或调用失败时，系统会自动降级为规则模式，采集、筛选和导出仍可继续使用。

## 数据位置

- 主数据库：`infohub.db`
- 日报导出：`exports/daily/YYYY-MM-DD/`
- 当前推荐入口使用源码和当前数据库，不优先使用旧打包 exe。

`infohub.db` 可能包含本机 DeepSeek API key，已通过 `.gitignore` 排除。不要手动上传数据库、`.env`、导出日报或虚拟环境。

## 开发运行

```bash
uv venv
uv pip install -r requirements-dev.txt
python start.py
```

测试和 CI 可使用临时数据库，避免碰本机数据：

```bash
set INFO_HUB_DB_PATH=%TEMP%\infohub-ci.db
set INFO_HUB_SKIP_INITIAL_FETCH=1
python src/main.py
```

## 本地验证

```bash
python -m py_compile start.py src/app_info.py src/config.py src/core_logic.py src/database.py src/deepseek_client.py src/ai_workflow.py src/workflow.py src/daily_renderer.py src/scheduler.py src/main.py src/routers/api.py src/routers/serializers.py src/routers/sse.py src/fetchers/rss.py src/fetchers/github.py src/fetchers/hackernews.py src/fetchers/arxiv.py src/fetchers/summarizer.py scripts/smoke_test.py
python -m pytest tests -q
python scripts/smoke_test.py
```

`scripts/smoke_test.py` 默认检查 `http://127.0.0.1:8000`，也可以通过 `INFO_HUB_BASE_URL` 指向其他本地地址。

## 主要目录

```text
info-hub/
├── 打开 AI 日报生产台.cmd   -> 给用户双击的中文入口
├── start.bat                -> Windows 启动包装器
├── start.py                 -> 检查服务、端口和启动源码服务
├── requirements.txt         -> 运行依赖
├── requirements-dev.txt     -> 开发、测试和打包依赖
├── CHANGELOG.md             -> 版本记录
├── docs/                    -> 上传和发布检查文档
├── scripts/smoke_test.py    -> 本地服务自检脚本
├── src/                     -> FastAPI 后端与前端页面
├── tests/                   -> 自动化测试
├── infohub.db               -> 本机数据，已忽略
├── exports/                 -> 日报导出，已忽略
└── release/                 -> 打包产物，已忽略
```

## GitHub 发布

上传前先看：

```text
docs/GIT_UPLOAD.md
docs/RELEASE_CHECKLIST.md
```

CI 会在 push 和 PR 时运行语法检查、单元测试和 smoke test。CI 不需要 DeepSeek API key，不读取本机 `infohub.db`，也不会触发自动采集。

## 重新打包 exe

如需重新生成可分发版本，运行：

```bat
uv pip install -r requirements-dev.txt
build.bat
```

打包输出在 `release/dist/info-hub/`。日常使用优先通过桌面快捷方式或 `打开 AI 日报生产台.cmd` 启动源码版本。
