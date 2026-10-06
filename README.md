# AstrBot Resource Monitor 📡

> **按客户端内容校验规则检测资源线路，并通过 AstrBot 发送故障与恢复通知。**

检查配置、清单、Range、块 MD5、热更包和证书等信息，识别“HTTP 200 但内容不可用”的故障。插件只负责观察与通知，不自动改配置或切换线路。

<a id="-架构与职责"></a>

**阅读导航**

[🏛️ 分层代码架构](#section-1) · [🚀 安装与配置](#section-2) · [⚙️ 常用命令](#section-3) · [🧪 验证](#section-4) · [⚙️ 配置来源与通知边界](#section-5) · [📜 许可](#section-6)

---

<a id="section-1"></a>

## 🏛️ 分层代码架构

AstrBot 依赖集中在 `main.py`。`Monitor` 组织一轮检查，来源适配和探针通过 `HttpClient` 获取数据，调度与告警状态单独维护；判据和状态模块无需导入机器人框架。

图中展示主要代码依赖：实线箭头指向被调用或被依赖的模块，虚线表示实现或生成关系；数据读写另用连线文字标明。

```mermaid
flowchart TB
    subgraph L0["框架适配层"]
        BOT["main.py · ResourceWatch"]
        CMD["commands / render"]
    end
    subgraph L1["应用编排层"]
        MON["runner.py · Monitor"]
    end
    subgraph L2["检查与状态领域"]
        SOURCE["sources / discovery"]
        PROBE["probes"]
        STATE["scheduler / state / models"]
    end
    subgraph L3["IO 适配层"]
        HTTP["HttpClient / AiohttpClient"]
        STORE["store.py"]
    end
    BOT --> CMD
    BOT --> MON
    BOT --> HTTP
    MON --> SOURCE
    MON --> PROBE
    MON --> STATE
    SOURCE --> HTTP
    PROBE --> HTTP
    STATE --> STORE
```

| 层次 | 源码入口 | 职责与边界 |
|---|---|---|
| 框架适配层 | [main.py · ResourceWatch](main.py) | 注册命令、定时任务、HTTP 实例与会话通知。 |
| 框架适配层 | [commands / render](watch/commands.py) | 解析操作、组织状态文本和通知文本。 |
| 应用编排层 | [runner.py · Monitor](watch/runner.py) | 协调发现、抽样、探针结果和告警状态。 |
| 检查与状态领域 | [sources / discovery](watch/sources.py) | 将配置源、清单和版本文档转换成检查输入。 |
| 检查与状态领域 | [probes](watch/probes.py) | 判定内容、Range、摘要与一致性等结果。 |
| 检查与状态领域 | [scheduler / state / models](watch/state.py) | 维护抽样覆盖、故障状态与恢复通知对象。 |
| IO 适配层 | [HttpClient / AiohttpClient](watch/http.py) | 提供可替换 HTTP 能力，测试使用假响应实现。 |
| IO 适配层 | [store.py](watch/store.py) | 负责本地 JSON 状态读写。 |

<a id="-安装与配置"></a>

<a id="section-2"></a>

## 🚀 安装与配置

1. 将仓库放入 AstrBot 的 `data/plugins/`，运行依赖见 [requirements.txt](requirements.txt)。
2. 在插件 WebUI 选择配置源：`entry_url` 指向配置文档，或 `mirrors` 直接提供线路表。
3. 配置 `notify.sessions`，用 `/线路 状态` 检查结果；多实例可用 `notify.prefix` 区分。

本地配置模板见 [config.example.json](config.example.json)，字段定义见 [_conf_schema.json](_conf_schema.json)。真实地址、通知会话与凭据只保存在部署侧。

开发护栏的下载地址与名单 API 同样由部署侧提供：安装使用 `HOOK_PACKAGE_URL`（兼容 `PKG_URL_DEFAULT`），名单查询使用 `CNB_API` 或安装目录策略的 `cnb_api`。源码不提供默认端点；缺少必要配置时安装或名单刷新会报错。具体流程见 [护栏部署说明](guardrails/README.md)。

<a id="-常用命令"></a>

<a id="section-3"></a>

## ⚙️ 常用命令

| 命令 | 用途 |
|---|---|
| `/线路 状态` | 检查结果与覆盖概况 |
| `/线路 测 <线路名>` | 手动检查指定线路 |
| `/线路 配置` | 配置摘要 |
| `/线路 静音 30m` / `/线路 取消静音` | 维护窗口 |
| `/线路 覆盖率` | 最近七天的块校验覆盖 |

内容判据取自线路清单；缺少阈值或热更声明时保持“未判定”。旧配置只能提供诊断线索，不能据此判定当前线路健康。配置层次、探针与通知限制见 [详细参考](docs/PROBES.md)。

<a id="-验证"></a>

<a id="section-4"></a>

## 🧪 验证

```sh
python3 tools/check-no-endpoints.py
python3 -m unittest discover -s tests -t .
python3 -m compileall -q watch main.py
```

测试无需 AstrBot 或真实线路。协作和提交要求见 [CONTRIBUTING.md](CONTRIBUTING.md)、[AGENTS.md](AGENTS.md) 与 [CLAUDE.md](CLAUDE.md)。代码采用 [GPLv3](LICENSE)。


<a id="section-5"></a>

## ⚙️ 配置来源与通知边界

| 来源 | 负责内容 |
|---|---|
| 插件本地配置 | 入口、通知会话、实例前缀与运行开关 |
| 线上配置与清单 | 线路、待检文件及客户端使用的判断依据 |
| 本地状态 | 连续故障、已通知状态、恢复与静音窗口 |

部署后先用状态命令检查配置是否完整，再验证故障与恢复通知。离线判据测试不会向真实会话发消息，也不能证明机器人平台的会话权限已经就绪。

<a id="section-6"></a>

## 📜 许可

代码采用 [GPLv3](LICENSE)。真实线路、会话 ID 与凭据不随源码或示例分发。
