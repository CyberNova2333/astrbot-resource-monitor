# 资源监控插件工作约定

## 检查入口

```sh
python tools/check-no-endpoints.py
python tools/check-branch-hygiene.py
python -m unittest discover -s tests -t .
python -m compileall -q watch main.py
```

判据测试离线喂假响应，不打真实线路；安装依赖后的连接层回归也使用替身。改 `watch/` 后必须跑测试。临时脚手架放仓库外，`tools/` 仅保留可重复使用的守卫与辅助。

## 项目红线

- 任何具体地址、凭据、会话 ID、文件端点、内部项目/仓库名称与资源管线细节不得进入源码、文档、测试、提交或 PR。示例一律 `example.test`，对外用中性功能称呼；保留凭据及相关变量标识的内容卫生约束。真实配置留部署侧。
- 线路、文件清单、超时、最低速率、换线判据来自线上同一份依据，不复制默认值兜底。取不到当前配置本身是 P0；旧配置只做诊断，不判绿。
- 判据层不依赖 AstrBot；框架 Star/Context/装饰器只在 `main.py` 接线。插件内部用包相对导入，不制造全局 `watch` 模块碰撞。
- 按 hash/客户端同源规则认内容，HTTP 200 不代表成功；未知结果不报确定故障、不累计验证覆盖。
- 只读观察，不写配置、不切源、不携带写权限凭据。HTTP、DNS 与每次重定向只允许公网，保留 SSRF 边界。
- 告警保留分级、窗口确认、去重、上游抑制、恢复与静音；每个接收者发送前重查恢复和静音，不能整批只检查一次。
- 状态持久化失败保留通知；QQ 官方成功调用只代表 submitted，保留查询/人工确认。UMO 首段是实例 ID；确认绑定本人、会话和刚查看的通知。纯文本、链接省略与提及降级必须保留。不要声称离线测试证明真实送达。
- 现有护栏/调度器自身出错按项目 fail-open 原则提示；探针不确定时宁可漏报。此规则不得被误用为“通知保存失败就确认送达”。
- 不写具体模型档位/版本和会话链接/标记；不以 Agent 或供应商 noreply 作为提交作者。

## 分支与提交

- 默认正式 `main`，无默认 PR；未经当前用户授权不提交/推送。禁止 Agent 命名分支，不用新分支触发 CI 或用 CI 代提交。
- 例外仅 `hotfix/<用途>`（24 小时）与 `surgery/<用途>`（72 小时），全会话最多一条。用途至少两个有意义的 kebab 词，非随机串、纯日期或泛称。已有可接续分支优先复用；远端非 main 在 2 小时内有活动且未删时不新开。
- 开分支前 `python tools/check-branch-hygiene.py --can-branch` 退出 0 并登记 `ACTIVE.md`。退役前对有价值内容先打 `archive/<原分支名>` tag 并确认远端，再合入后退役；不得把 archive/research 当长期分支。
- 标题 `type(scope): 中文描述`，允许 `feat fix refactor docs test chore ci perf build`；一功能一提交，正文说明原因，结尾 `文档: …` 交代变化或具体不影响原因。
- 作者按实际人类参与者记，没有默认值，不确定先确认；Agent 仅 co-author，完整 `Name <email>`。已登记 `Claude <noreply@anthropic.com>` 和 `Codex <noreply@openai.com>`，新 Agent 首次贡献时登记。
- 所有非初始提交必须 SSH 签名，不用未签名提交或 Agent 通用密钥；私钥留本机，只交公钥登记。历史克隆迁移遵守 README，不把旧历史合并或推回。

## 现有护栏与协作

保留 `.claude/settings.json`/`.codex/config.toml` → `tools/agent-guard.py` → `tools/githooks/` 接线；备用人工安装是 `bash tools/install-hooks.sh`，Windows 可用 `tools/install-hooks.cmd`。
`commit-msg` 检查中文 Conventional 标题、完整 co-author 和文档交代；`pre-push` 另检查新增提交实际内容与分支纪律。保留 POSIX sh 启动层、Python 解释器探测和 LF，缺解释器时放行并提示。
Agent guard 拦 `--no-verify`、`-n` 及覆盖 hooksPath 的绕过。已记录人工逃生口为顶格独占行 `[skip-hooks]`、`SKIP_MSG_HOOK`、`SKIP_ENDPOINT_HOOK`、`SKIP_BRANCH_HOOK`；使用须有明确人工决定并说明原因，不是默认豁免。
护栏用于防误操作，不能宣称本机不可绕过的安全边界。规则统一在本文件；冲突先说明，遵守当前明确任务授权和上级指令，不让通用分支模板自动改变项目流程。


## Repo docs

The living guide is [repo-docs/README.md](repo-docs/README.md); start with the [main walkthrough](repo-docs/walkthroughs/one-real-run.md), then use the [code map](repo-docs/code-map.md) to locate changes.
This repo's `repo-docs/` guide is reader-facing Chinese documentation. When updating reader-facing guide pages, use `repo-docs-zh` when available; keep Chinese reader handles in the prose and preserve exact source identifiers for lookup.
Read current source, scripts, configuration and tests before relying on guide claims. Repo questions, behavior-changing edits, user uncertainty, stable knowledge clarified in conversation and knowledge about to enter memory trigger the `repo-docs` Sync gate before the final response (or the same manual check if the skill is unavailable).
Choose `none`, `answer-only`, `foreground patch`, or `background sync`. Patch the smallest owning page before answering when stale content would mislead; delegate broader non-critical sync only with a real tracked handoff. Record meaningful guide changes and validation limits in `repo-docs/change-log.md`, with `Synced through <sha>` when HEAD exists. Do not log every answer.


## 贡献与维护入口

提交采用 Conventional Commits：`type(scope): 描述`；项目已有的中文描述、署名、签名和文档交代要求继续生效。保留用户未提交内容，只暂存本次明确审查的路径。
贡献与安全约定分别见 [贡献说明](CONTRIBUTING.md) 和 [安全说明](SECURITY.md)；相关维护由统一任务协调，避免并行覆盖。
维护守卫安装命令为 `python tools/repo_maintenance_guard.py install`。仅在明确安装任务下执行；文档修改不自动安装或更改 Git 配置。保留已有安全钩子，安装与验证结果按实际执行另行记录。

文档站统一使用 VitePress 默认主题；样式与动效遵循原生主题，构建输出独立于业务界面。

## 项目简介与主页元数据 (meta.json)

- **项目名称**：AstrBot Resource Monitor · 资源下载线路检查与告警插件
- **项目简介**：用于 AstrBot 的资源线路定时检查插件，除了看 HTTP 状态码外，还会按清单抽查 Range 分块、文件 MD5 和证书有效期，发现异常时发送消息提醒。
- **公开状态**：已公开 (public) · 分类：`cloud-edge` · 主语言：`Python`
- **元数据说明**：仓库根目录的 [`meta.json`](meta.json) 供个人主页（[`cybernova-homepage`](https://github.com/CyberNova2333/cybernova-homepage)）读取项目简介、功能说明、技术栈和常用命令。修改项目主要功能、技术栈或文档站链接时请同步更新 `meta.json`。
