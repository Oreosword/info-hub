# Changelog

## 0.1.1 - 2026-06-16

GitHub v1.1 打磨版本。

- 增加 GitHub Actions CI，覆盖语法检查、单元测试和本地服务 smoke test。
- 增加 `INFO_HUB_DB_PATH`、`INFO_HUB_SKIP_INITIAL_FETCH` 和 `INFO_HUB_BASE_URL`，让测试和 CI 不触碰本机数据库、不触发自动采集。
- 增加 `tests/` 自动化测试，覆盖 URL 规范化、内容 hash、状态规则、中文简介和 DeepSeek 设置脱敏。
- 抽出 `src/core_logic.py`，集中纯逻辑规则。
- 抽出 `src/routers/serializers.py`，减少 API 路由文件中的重复转换代码。
- 增加 Issue 模板、PR 模板和发布检查清单。
- 更新 README，补充 GitHub、CI、开发验证和数据安全说明。

## 0.1.0 - 2026-06-11

首个可上传 Git 的源码版本。

- 完成信息流、筛选台、日报生成的本地闭环。
- 支持 DeepSeek API 设置、连接测试、候选重分析和规则降级。
- 支持英文资讯简介中文化和最近简介回填。
- 支持 Markdown / HTML 日报导出。
- 增加桌面快捷方式和项目根目录中文启动入口。
- 增加版本信息、Git 忽略规则、开发依赖和 smoke test。
