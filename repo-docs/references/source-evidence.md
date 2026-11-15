# 源码证据审计

这是固定审计记录，记录按当前提交基线对全仓库源码与离线测试开展的两遍核查；机制讲解由主流程页和模块页承载，文件索引由代码地图承载。

## 遍历记录

| 遍历 | 实际检查 | 得到的依据 |
| --- | --- | --- |
| Pass 1 | 全仓结构、`AGENTS.md`、`main.py`、`_conf_schema.json`、`config.example.json`、`metadata.yaml`、`requirements.txt`、`.github/workflows/main-checks.yml`、`tools/check-no-endpoints.py` 及待迁出清退的原探针独立说明页 | 核准仓库真实定位为 AstrBot 资源分发线路监控插件，清理无代码引用的独立草稿并排查与运行时字段差异 |
| Pass 2 | `watch/` 全模块（`config.py`、`sources.py`、`discovery.py`、`http.py`、`probes.py`、`runner.py`、`scheduler.py`、`state.py`、`store.py`、`commands.py`、`render.py`、`models.py`）及 `tests/` 20 个测试文件 | 逐一确认配置源归一化、10 项探针、7 天轮转、两级抑制、64 MiB 上限、公网校验、文本净化与 QQ 官方确认细节 |

## 覆盖与排除

本轮升级为 Standard 全覆盖包，涵盖 `main.py` 框架适配、全部 10 项探针与快慢调度、`watch/sources.py` 配置源与降级诊断、`watch/state.py` 滑动窗口、静音与队列落盘，以及 `watch/http.py` / `commands.py` / `render.py` 安全边界；原零散探测说明已全部迁入本指南与 `docs-site/` 后移除。本包仅验证离线替身单元测试与地址守卫，不覆盖未安装 `aiohttp` 时的实网会话层、真实 AstrBot 宿主、公网镜像环境及 QQ 官方平台实际送达。

## 声明与证据

| Claim | Evidence | Confidence | Caveat | Used by |
| --- | --- | --- | --- | --- |
| 配置源支持 endpoint 与 mirrors 且运行时优先读 WebUI 再兜底环境变量文件 | [config.py](../../watch/config.py) 与 [sources.py](../../watch/sources.py) 的 `load`、`build`；[test_config.py](../../tests/test_config.py) | 已确认 | `config.example.json` 仍存在未消费的旧示例键名 `fire_after`/`recover_after` | 配置源与降级页 |
| 入口失联后仅借未超龄快照作诊断提示，标 `unknown=True` 且不判绿不告警 | [runner.py](../../watch/runner.py) 的 `_diagnose_entry_failure`；[test_runner.py](../../tests/test_runner.py) `EntryDownDiagnosisTest` | 已确认 | 需部署侧先成功拉取至少一次健康快照才可用 | 主流程 Step 1；配置源与降级页 |
| 10 项探针分快慢双锁与并发信号量运行，手动 `/线路 测` 禁用整包核对，慢下载期间配置变化不污染新调度 | [probes.py](../../watch/probes.py)、[runner.py](../../watch/runner.py) 的 `_slow_round`（`allow_heavy=False`）；[test_probes.py](../../tests/test_probes.py) | 已确认 | 分块与一致性基线依赖过半数有效清单 | 主流程 Step 2；探针与轮转页 |
| 每个接收者发送前重检静音与恢复，QQ 官方只记 `submitted` 并绑定 `/线路 通知` 查看者与管理员 `/线路 确认` | [main.py](../../main.py) 的 `_flush_outbox`、`_discard_stale`、`_pending_notification`、`_confirm_notification`；[test_delivery.py](../../tests/test_delivery.py)、[test_qq_official.py](../../tests/test_qq_official.py) | 已确认 | 离线使用 `astrbot_stub`，真实官方配额需部署验收 | 主流程 Step 3–4；告警与投递页 |
| HTTP 禁 Cookie、禁环境代理、逐跳核验公网地址与 `MAX_BUFFER_BYTES = 64 MiB`，TLS 共用公网校验与 SNI，输出经 `safe()` 清洗 | [http.py](../../watch/http.py)、[probes.py](../../watch/probes.py) `_tls_not_after`、[render.py](../../watch/render.py) `safe`；[test_network_regressions.py](../../tests/test_network_regressions.py) | 已确认 | 无 `aiohttp` 时 5 项 `AiohttpBoundaryTest` 会被跳过 | 安全与闸门页 |

## 证伪检查与读者下一问

证伪检查：若官方平台发出消息后立即清空队列而不待 `/线路 确认`、允许跨会话或非管理员确认、快周期发现恢复后仍继续向第二个群发送过期故障、`chunk_size` 能抬高进程缓存上限，或缺失阈值时不标 `unknown=True` 而硬编码默认速度判红，则对应模块说明即失效。

读者下一问：如果需要新增第三种配置源形状、调整某项探针的判定逻辑，或排查 `config.example.json` 与 `_conf_schema.json` 的键名对照，请分别从[配置源与降级说明](../modules/sources-and-degraded.md)、[十项探针判据与分块轮转](../modules/probes-and-rotation.md)与[代码地图](../code-map.md)查找对应测试入口。

## 验证边界

本轮执行 `python3 -m unittest discover -s tests -t . -v`、`python3 tools/check-no-endpoints.py --verbose`、`python3 -m compileall -q tools watch main.py`、`validate_repo_docs.py` 及 `pnpm --dir docs-site run docs:build`。其中系统 Python 环境缺少 `aiohttp`，导致 [test_network_regressions.py](../../tests/test_network_regressions.py) 内 5 项 `AiohttpBoundaryTest` 跳过，其余 247 项单元测试均运行核对；所有端到端联网与聊天平台行为仍以部署侧运行验收为准。
