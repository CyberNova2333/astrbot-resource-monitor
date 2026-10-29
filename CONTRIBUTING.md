# CONTRIBUTING.md — 怎么一起干活

> 本文件是协作约定；技术档案看 [README.md](README.md)，Agent 硬约束看
> [CLAUDE.md](CLAUDE.md) / [AGENTS.md](AGENTS.md)。
> 三者有冲突时：CLAUDE.md > AGENTS.md > 本文件。

## 一、分支结构：一根主线 + 两类例外

```
main（唯一长期分支）
├── 日常开发：所有人直接提交
├── 例外1：hotfix/<用途> —— 修主线红灯，寿命以小时计（上限 24 h）
└── 例外2：surgery/<用途> —— 判据层/调度层大重构，寿命 ≤ 72 h
```

- 禁止第三类分支；**不存在以 Agent 名字开头的分支**（`claude/…`、`codex/…`）
  ——分支名要回答「在干什么」，不是「谁开的」（AGENTS.md §0 规则一）；
- `surgery/*` 开工前在 [ACTIVE.md](ACTIVE.md) 登记，完工立即合入删除；
- 用完即退役：有价值的先打 `archive/<原分支名>` tag 存档再删。

## 二、提交规则

1. **一个逻辑改动一个 commit**，禁止攒批量提交（攒提交 = 把 rebase 冲突攒成
   炸弹）；
2. 提交前必过本地自检（命令见 AGENTS.md §3）；
3. `git config pull.rebase true` + `rebase.autoStash true` +
   `rerere.enabled true`，开工第一件事就是 rebase 到最新 main；
4. Commit message 用 **Conventional Commits 前缀 + 中文描述**，署名规则见
   AGENTS.md §1 三（**Agent 永远只做 co-author**）；
5. **分层验证**——按改动路径决定验证级别：

   | 改动路径 | 进入 main 的要求 |
   |---|---|
   | 文档、注释 | 守卫脚本通过 |
   | 渲染层、命令、配置 schema | + 判据层测试全绿 |
   | 探针判据、状态机、调度 | + **对着真线路跑过一轮**（本地手动，别写进测试） |

   第三级 CI 替代不了：判据层测试刻意不联网（AGENTS.md §3），所以「这个探针
   在真网络上到底会不会误报」只能人跑一次。

## 三、对外表述：只说角色，不写具体出处

注释、文档、提交信息里提到**本仓库之外**的东西时，只说它在功能上是什么，
不写具体出处：

| 写这个 | 不写这个 |
|---|---|
| 线上配置端点（地址由本地配置给） | 具体域名 / 路径 / 谁托管的 |
| 一条线路 / 线路表 | 具体 CDN 厂商、具体 base URL |
| 通知会话（ID 由部署侧配置给） | 具体群号 / 会话 ID |
| 上游发布侧 | 那边是什么、在哪、由谁同步 |

理由是**读代码的人要的信息一点没少**：他要知道的是「这个值不归我管、改要去
那边改」，出处叫什么对他没有增量；而写上去之后，这个仓库就替别处做了它自己
没做的宣告。地址一律由部署侧配置给，源码与历史里都不出现（CLAUDE.md 铁律 1）。

同一条规矩延伸出两点，容易漏：

1. **守卫不能去钉那个名字。** 「注释里必须提到某某」这种断言，钉的方式就是把
   名字写进守卫——守卫自己就成了写回来的那一处。改成钉角色（例如「示例地址
   必须是 `example.test`」，`tools/check-no-endpoints.py` 就是这么写的）。
2. **提交信息同样算对外表述**，而且它比源码更难改：源码改一行就好，提交信息
   要重写历史。

> ⚠ 这条与「提交必须交代 why」互相拉扯：交代 why 的本能会让人把「为什么不写」
> 也一起写上去，而那句话本身就是不该写的东西。判据很简单——**只写「我们的
> 约定是什么」，不写「别处是什么状况」**。

## 四、配置与凭证：三层边界

| 层 | 放什么 | 存在哪 | 谁能改 |
|---|---|---|---|
| 插件源码 | 判据的形状 | 本仓库 | 提 main |
| 本地配置 | 入口地址、通知会话 ID、凭证、本地开关 | 部署机（AstrBot 插件配置或本地配置文件） | 部署者 |
| 线上配置 | 线路表、文件清单、内容判据、阈值 | 线上配置端点 | 那边的维护者 |

三条边界规则：

- **本地配置只给一个入口**。凡是「线上已经有一份」的东西（线路表、阈值），
  本地配置里再放一份就是第二份判据，会漂移（CLAUDE.md 铁律 2）。
- **凭证只走本地配置或 CI secret**，且监控只需要只读权限——它不该有能力改任何
  东西（铁律 5）。
- **样例配置一律 `example.test`**，文件名一律 `*.example.*`；真配置的文件名已经
  在 `.gitignore` 里挡住，但挡不住手滑改名，所以守卫再拦一道。

## 五、CI

```
push 到 main / 例外分支
 └── main-checks.yml
      ├── 地址守卫    tools/check-no-endpoints.py
      ├── 判据层测试  pytest（离线）
      └── 语法        compileall
```

- CI 只做**检查**，不发布、不部署、不改仓库内容；
- workflow 不做自动发版；一次性 workflow（`*-once.yml`）禁止入库（AGENTS.md §4）；
- **CI 不是唯一防线**：地址守卫在 pre-push 就拦了一道，因为等 CI 红的时候，
  东西已经在远端历史里了。

## 六、红灯协议（main 挂了怎么办）

1. CI 失败 = 🔴 红灯。红灯期间只允许**修复主线**的提交，新功能本地继续但先别推；
2. 引入者负责修，修不了就 `git revert` 先恢复绿灯，问题回炉；
3. 找不到引入者 → `git bisect` 定位。

红灯这件事没有做成钩子硬拦（本仓库还没有那么多流量），靠自觉 + CI 的红叉。

## 七、最低限度沟通

- [ACTIVE.md](ACTIVE.md)：每人/每个 Agent 开工时加一行
  `日期 | 人 | 在搞什么 | 预计动哪片`，完工删行。10 秒成本，消灭最严重的对撞；
- 三件事必须说一声：**红灯、surgery 分支开工、告警策略改动**（最后一条会直接
  改变群里收到多少消息，属于会影响别人的改动）。其余免沟通。

## 八、明确不做的事

边界写在 README「明确不做的事」，这里只补一句关于**范围蔓延**的：

监控最容易长歪的方向是「顺手也监控一下 X」。判据是——**这个告警响了，收到的人
能做什么？** 做不了任何事的告警不要加：它只会消耗大家对告警的信任，而信任一旦
掉下去，真正的 P0 也没人看了。

<!-- repo-maintenance:begin -->
## 提交与核验 / Commits and verification

先阅读 [Agent 操作约束](AGENTS.md)、[项目指南](repo-docs/README.md) 和 [安全说明](SECURITY.md)。项目自己的兼容性、测试、署名与签名要求继续适用。

Use the project instructions, living guide and security policy before changing code. Existing compatibility, testing, attribution and signing requirements remain authoritative.

提交标题采用 `type(scope): 描述`，`scope` 可省略；允许 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`revert`、`data`。标题不超过 100 个字符；仓库规定中文或更严格的类型集合时，遵守该仓库要求。正文解释原因、影响、实际验证结果和文档影响。一条提交对应一个可审阅的主题，签名和参与者尾注按真实身份填写。

Use Conventional Commits, with an optional scope and a subject of at most 100 characters. Follow stricter repository rules, including Chinese subjects where required. Explain the reason, effect, actual verification and documentation impact in the body. Attribute the real participants and retain the configured signing identity.

```sh
python tools/repo_maintenance_guard.py install
python tools/repo_maintenance_guard.py status
python tools/repo_maintenance_guard.py pre-commit
```

安装只修改当前克隆的 Git 配置。已有钩子会继续执行；新克隆需要重新安装。提交模板位于 `.gitmessage.txt`，已有自定义模板不会被覆盖。Git 钩子需要 Python 3.10+，不可完成检查时阻止本次操作并说明原因。项目自身的构建与测试命令见 README 和指南，安全扫描通过不代表业务测试通过。

Installation changes only this clone's Git configuration. Existing hooks continue to run. Install again in each fresh clone; an existing commit template is retained. Python 3.10+ is required. A failed security check stops the operation. Run the build and tests documented by this repository; passing the security scan does not establish application correctness.

历史信息整理仅用于维护者明确授权的场景。改写会改变提交编号；保持作者、提交者、日期、文件树与父图关系，保留原始引用和映射，并重新验证签名。发布改写后的历史需要独立核对远端引用与协作者状态。

Rewriting history requires an explicit maintenance request. Preserve identities, dates, trees, graph relationships and recovery references, then verify new signatures. Review remote state and collaborator impact separately before publishing rewritten history.
<!-- repo-maintenance:end -->
