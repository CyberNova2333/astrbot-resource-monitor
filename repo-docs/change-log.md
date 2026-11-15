# 指南变更记录

## 2026-11-15 20:50 CST：全面重置文档体系并升级 Standard 源码指南

- 触发：全工作区文档重置，彻底清除此前面向主机性能监控的模板幻觉文本，并将分散在旧版 `docs/PROBES.md` 中的全部技术事实并入 `docs-site/` 与 `repo-docs/` 后移除冗余散页。
- 扩展为 Standard 包：新增 4 篇概念模块（[配置源、分层与过期降级](modules/sources-and-degraded.md)、[十项探针判据、多数共识与分块轮转](modules/probes-and-rotation.md)、[告警抑制窗口、持久化队列与人工确认](modules/alert-state-and-delivery.md)、[目标校验、响应上限与命令闸门](modules/security-and-gates.md)）及[术语表](glossary.md)，同步更新主入口、真实运行主流程、代码地图与两份审计记录。
- 纠偏与补充：依据 `main.py`、`watch/` 源码、`_conf_schema.json`、`config.example.json` 与 `tests/` 全部 20 个测试文件，补全 10 项探针全表、两级抑制键、7 天轮转覆盖、`PublicResolver` / `64 MiB` / `render.safe()` 防护边界，以及 `config.example.json` 与运行期告警键名差异说明。
- 验证：本轮运行 `validate_repo_docs.py`（Standard 模式）、`python3 tools/check-no-endpoints.py --verbose`、`python3 -m unittest discover -s tests -t . -v`、`python3 -m compileall -q tools watch main.py` 及 VitePress 站点构建。

Synced through 8777215a96373c8b67299a0ce8955469b905f37b

## 2026-10-29 22:00 CST：文档站迁移为 VitePress 默认主题

按维护任务统一切换站点工具链至 VitePress 1.6.4 默认主题并补充锁文件守卫检验；早期构建与审计基线保留作历史参照（原 Lite 范围已由本轮 Standard 重置覆盖）。
