# 源码证据审计

这是固定审计记录，记录 2026-10-29 的两遍调查；行为解释由主流程页承载，源码导航由代码地图承载。

## 遍历记录

| 遍历 | 实际检查 | 得到的依据 |
| --- | --- | --- |
| Pass 1 | 仓库目录、Git 状态、父级及 root AGENTS/CLAUDE、README、`main.py` 的包加载与命令入口、`requirements.txt`、现有 `docs/PROBES.md` 和 CI 配置 | 确定真实入口、运行命令及现存文档；README 只作线索 |
| Pass 2 | `watch/runner.py`、`watch/state.py`，`main.py` 的逐接收者投递与查询确认分支，`tests/test_delivery.py`、`test_qq_official.py` 和监控回归 | 追踪主路径的输入、输出与失败分支，并对照测试断言 |

## 覆盖与排除

覆盖：一轮配置发现和内容检查到 QQ 官方通知查询与确认。不逐项覆盖所有探针算法、慢周期整包下载和每个平台适配器；没有真实 AstrBot/QQ 交互或云端线路验收，不提供自动修复或内网监控。


## 声明与证据

| Claim | Evidence | Confidence | Caveat | Used by |
| --- | --- | --- | --- | --- |
| 上次好配置仅作诊断，不用于判绿 | [编排器](../../watch/runner.py) 搜索 `last_good_snapshot` | 已确认 | 当前配置失败仍需保留未判定状态 | 主流程 Step 1–2 |
| 每个接收者前重查静音与过期故障 | [入口](../../main.py) 搜索 `_discard_stale`；[回归](../../tests/test_delivery.py) | 已确认 | 本轮未跑，远端送达未验证 | 主流程 Step 3 |
| 官方发送成功调用只记录 submitted | [投递](../../main.py) 搜索 `submitted`；[官方测试](../../tests/test_qq_official.py) | 已确认 | 不代表平台或真人收到 | 主流程 Step 4 |
| 查询不清除，确认绑定用户/会话/通知 | [查询与确认](../../main.py) 搜索 `_shown_notifications` | 已确认 | 重启后重新查看；保存失败不确认 | 主流程 Step 4 |

## 证伪检查与读者下一问

证伪检查：若官方发送后直接清除队列、跨用户确认通知，或第一个接收者等待期间恢复后仍向第二个发送过期故障，这份通知模型就失效。应对照投递与官方确认回归逐项核对。

读者下一问：某类 Range 或热更内容具体怎样判失败？从原有 `docs/PROBES.md` 与 `watch/probes.py`、对应探针测试继续；本页不覆盖所有判据。

## 验证边界

本轮执行 `validate_repo_docs.py` 和 MkDocs 构建，退出码及完整输出保存在独立维护报告中；不将静态阅读当作业务测试通过。没有部署、生产验收或历史改写。
所有 `../../` 源码链接按当前磁盘核对；独立站点没有这些仓库文件，MkDocs 对此记 INFO，站内链接仍正常检查。未解析、展示或引用真实凭据和运行时数据库内容；现有未提交文件仅作本地摘要保全。
