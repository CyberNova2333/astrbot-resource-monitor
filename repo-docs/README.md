# AstrBot Resource Monitor：源码与架构指南

监控资源分发线路时，不能只看请求是否返回成功状态码，因为静默回退、半截缓存、忽略分片请求以及镜像滞后往往同样返回 HTTP 200。这个插件按照客户端的校验口径从配置源现场发现线路与阈值，核对清单、分片、校验和与证书到期，经由多轮故障窗口与抑制树去重后写入持久化队列，并在 QQ 官方适配器中把「已尝试提交」和「管理员人工核销」区分开。

这里记录插件内部如何从定时巡检一步步变成可确认的通知，适合想理解机制、排查行为或修改代码的维护者。对普通部署者与配置者的操作说明见项目根入口与文档站，第一步可[沿一次真实巡检与确认走到底](walkthroughs/one-real-run.md)。

## 阅读路径

| 读者目标 | 从这里开始 | 读完后获得什么 |
| --- | --- | --- |
| 第一次理解主流程 | [沿一次真实巡检与确认走到底](walkthroughs/one-real-run.md) | 串联配置发现、内容核对、队列落盘与 QQ 确认的交接和失败边界 |
| 理解配置来源与降级 | [配置源、分层与过期降级](modules/sources-and-degraded.md) | 分清三层配置职责、两种配置源差异及入口失联时的安全诊断边界 |
| 理解探针判据与轮转 | [十项探针判据、多数共识与分块轮转](modules/probes-and-rotation.md) | 掌握十项检查触发条件、多数一致口径、7 天覆盖统计与快慢锁隔离 |
| 理解状态收敛与投递 | [告警抑制窗口、持久化队列与人工确认](modules/alert-state-and-delivery.md) | 理解 M-of-N 窗口、两级抑制、静音恢复、逐接收者复核与官方确认 |
| 理解安全边界与净化 | [目标校验、响应上限与命令闸门](modules/security-and-gates.md) | 看清公网地址绑定、64 MiB 内存闸门、指令限频及出群防注入机制 |
| 准备修改源码或测试 | [按职责与测试寻找修改入口](code-map.md) | 快速定位负责模块、关键符号、回归测试文件与明确排除的范围 |
| 查阅项目高频术语 | [查看项目核心术语对照](glossary.md) | 分清配置源、未判定、抑制键、轮转覆盖与官方确认等易混概念 |
| 审核源码证据覆盖 | [核对源码调查与验证范围](references/source-evidence.md) | 确认每条机制结论对应的代码依据、测试验证与未核实环境边界 |
| 检查文档质量与风险 | [查看读者模拟与剩余风险](references/quality-review.md) | 了解核心难点的讲解闭环、证伪检查条件与剩余部署验收要求 |
| 查看文档同步历史 | [查看指南变更与同步基线](change-log.md) | 追溯文档升级决策、工作树基线提交与验证边界说明 |

## 运行与验证

插件部署在 AstrBot 插件目录，依赖 Python 3.10+ 与 `requirements.txt` 中的 `aiohttp`；实际入口地址、镜像域名与通知会话只保留在部署侧面板或独立配置文件。离线代码验证与文档构建入口如下：

```sh
python3 -m unittest discover -s tests -t . -v
python3 tools/check-no-endpoints.py --verbose
python3 -m compileall -q tools watch main.py
pnpm --dir docs-site install --frozen-lockfile && pnpm --dir docs-site run docs:build
```

离线单元测试使用本地假 HTTP 客户端与 AstrBot 替身模块，其中网络层与真实 `aiohttp` 会话相关的 5 项边界测试在未安装 `aiohttp` 的系统 Python 环境下会自动跳过，已在文档校验与变更记录中按实标注。真实 AstrBot 宿主加载、群内 `/线路` 交互与 QQ 官方送达仍需在部署环境中另行验收。

证据状态：除特别标注外，本页基于当前源码已确认。
