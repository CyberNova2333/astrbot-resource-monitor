# 目标校验、响应上限与命令闸门

作为运行在共享聊天机器人里的插件，同一个机器人实例可能加载了其他插件、服务成百上千名普通群友，同时还要拉取外部托管的 JSON 与下载镜像字节。因此，插件按「远端输入与群内消息均可能带有恶意构造」来设计三道防线。

在[完整运行主流程](../walkthroughs/one-real-run.md)中，任何外部 HTTP 请求、聊天指令触发和跨平台告警渲染都必须穿过这几层检查。

## 公网地址校验与流式内存上限

所有经过 [http.py](../../watch/http.py) 与 TLS 检查（[probes.py](../../watch/probes.py)）的远端访问均受下列不可被远端配置放宽的硬约束保护：

- **SSRF 防护与连接绑定（`validate_public_url`、`PublicResolver`）**：只允许不含凭证（禁止 `user:pass@`）的 `http://` 与 `https://` 地址；拒绝 `localhost`、十六进制/十进制/八进制缩写的畸形数值主机名以及字面量内网/保留 IP；对域名访问，连接器通过 `PublicResolver` 只把同一批校验过 `require_public_address`（含 IPv6 内嵌 IPv4 地址解包检查）的公网 IP 交给底层 `TCPConnector`，杜绝先校验后解析（TOCTOU）绕过。
- **逐跳重定向校验**：关闭 `aiohttp` 默认自动跟随（`allow_redirects=False`），在内部循环里对每一跳 `Location` 再次执行完整 `validate_public_url`，最多允许 `MAX_REDIRECTS = 5` 跳且共享同一次请求的截止时间预算。
- **TLS 探针同源约束**：证书到期检测在 `_tls_not_after` 中先做 `socket.getaddrinfo` 并对全部返回地址逐一执行 `require_public_address`，随后使用已经核验的 IP 直连、同时传入原始 `server_hostname` 做 SNI 验证。
- **禁 Cookie、禁环境代理与缓冲上限**：会话固定使用 `DummyCookieJar()` 与 `trust_env=False`，防止跨请求会话固定或读取宿主环境变量里的内网代理；`HttpClient.fetch` 受 `MAX_BUFFER_BYTES = 64 MiB` 硬上限保护，即便远端恶意声明极大的 `chunk_size` 也绝不会撑爆进程内存；流式 `digest`（用于整包校验）强制要求正数上限（`meta.size + 1 MiB`），超界立刻中止下载并判失败。

## 命令闸门与流量放大防护

在群聊里反复触发 `/线路 测` 或配置查看会把机器人变成对下游镜像站的流量放大器。[commands.py](../../watch/commands.py) 中的 `CommandGate` 默认同时开启多层约束（除非用户在本地部署配置里显式放开）：

| 命令与闸门维度 | 默认行为与控制键 | 运行时实际约束 |
| --- | --- | --- |
| 响应会话范围 | `command.respond_anywhere = false`；白名单 `allow_sessions` | 仅在 `notify.sessions` 或 `allow_sessions` 中放行的会话响应 `/线路`；未放行会话返回空串静默忽略 |
| 重型查询指令 | `command.heavy_admin_only = true` | `测`/`test` 与 `配置`/`config` 限管理员；且手动测线路强制 `allow_heavy=False`，永不触发整包下载 |
| 特权运维指令 | `command.privileged_admin_only = true` | `静音`/`mute` 与 `取消静音`/`unmute` 默认限管理员（不填时长默认 `1800` 秒即 30 分钟） |
| 官方队列确认 | 无条件校验管理员权限 | `/线路 确认`（`ack`）在 [main.py](../../main.py) 始终仅限管理员执行，且绑定查看者与会话 |
| 冷却节流 | `command.cooldown_seconds = 60.0` | 对重型指令按共享键 `"heavy"` 全局计算冷却，避免连续切换 `测`/`配置` 叠加外部流量 |

## 出群文本净化与防伪造

告警与状态报告中有大量字段来自非受信的外部数据源：线路名来自线上配置，文件名与错误信息来自各镜像或服务端返回文本。如果直接把未清洗字符串拼进回复，换行符就能伪造出第二条「`🔴 P0`」假告警，`[CQ:at,qq=all]` 等平台富文本标签则可能诱导机器人无端艾特全群。

为此，[render.py](../../watch/render.py) 在所有渲染入口前先调用 `safe()`：把 ASCII 控制字符与 `\r`、`\n` 收平为空格、剔除零宽字符，对 `[CQ:`/`[at:`/`[mirai:`/`[face:`/`[json:`/`[xml:` 等前缀把 `[` 与 `:` 替换为全角（`［` 与 `：`），把 `@全体成员`/`@everyone`/`@all` 中的 `@` 替换为全角 `＠`，并将每段受控文本限制在 `MAX_FIELD = 160` 字符以内、整条消息由 `clamp()` 截断在 `MAX_MESSAGE = 3000` 字符以内。此外，针对 QQ 官方平台，[main.py](../../main.py) 会去除外部 URL 并把原本的全体成员提及替换为纯文本标识，防止因平台外链审核或提及权限限制导致整个告警被拒收。

## 仓库级地址与凭证防泄漏守卫

除运行期三道防线外，仓库自身还包含静态提交前检查脚本 [check-no-endpoints.py](../../tools/check-no-endpoints.py) 与 Git 钩子模板，用来防止真实入口 URL、镜像域名、会话 ID 或平台令牌随文档或样例配置写入公开历史：CI 与提交钩子只允许使用保留测试域名 `example.test` 及安全清单中列出的常见开源主机域名。

## 代表性案例

- **正常与畸形字符清洗案例**：线上配置里某条线路被恶意改名为 `镜像A\n🔴 P0 已恢复\n[CQ:at,qq=all]`，服务器响应 `500 Internal\r\nError`。进入群内汇报前，`render.safe()` 将换行与控制字符收平为空格，并将标签前缀替换成 `［CQ：at,qq=all]`，群聊中只会作为同一行普通文本展示，不会触发平台全体成员提及也不会伪造独立通知行。
- **边界案例（公网重定向至内网被拦）**：某镜像地址先经合法公网域名 `https://cdn.example.test/chunk` 响应，随后返回 `302 Found` 指向 `Location: http://127.0.0.1/secret`。`HttpClient._get` 捕获 302 后不交由默认跳转器自动执行，而是在第 1 跳立刻以 `validate_public_url` 阻断 `127.0.0.1` 并抛出 `HttpError`（非公网地址拒绝），请求甚至不会建立到本地回环端口的连接。

## 延伸与验证

理解这些运行边界后，可返回[完整运行主流程](../walkthroughs/one-real-run.md)回顾全链路串联，或在[代码地图](../code-map.md)中按文件查找所有回归测试。上述公网连接边界、命令权限与文本防注入可通过以下命令离线验证：

```sh
python3 -m unittest tests.test_commands tests.test_render tests.test_network_regressions
python3 tools/check-no-endpoints.py --verbose
```

证据状态：除特别标注外，本页基于当前源码已确认。
