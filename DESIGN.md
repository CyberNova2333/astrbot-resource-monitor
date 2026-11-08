---
version: 2.0.0
name: AstrBot Resource Monitor Primer Tactile Design System
description: 面向 AstrBot 资源线路检测与故障恢复通知插件（astrbot-resource-monitor）的 Primer 质感设计系统规范。将 GitHub Primer 功能原语与遥测仪表盘（Telemetry HUD）硬件美学深度融合，定义探针状态指示灯、Range/MD5 校验健康卡片、告警消息卡片与控制台视觉契约。
colors:
  primary: '#0969da'
  accent-fg: '#0969da'
  accent-emphasis: '#0969da'
  accent-subtle: '#ddf4ff'
  accent-dark-fg: '#2f81f7'
  canvas-default: '#ffffff'
  canvas-overlay: '#ffffff'
  canvas-inset: '#f6f8fa'
  canvas-subtle: '#f6f8fa'
  canvas-dark-default: '#0d1117'
  canvas-dark-overlay: '#161b22'
  canvas-dark-inset: '#010409'
  canvas-dark-subtle: '#161b22'
  fg-default: '#1f2328'
  fg-muted: '#57606a'
  fg-on-emphasis: '#ffffff'
  fg-dark-default: '#f0f6fc'
  fg-dark-muted: '#8b949e'
  border-default: '#d0d7de'
  border-muted: '#d8dee4'
  border-dark-default: '#30363d'
  border-dark-muted: '#21262d'
  success-fg: '#1a7f37'
  success-emphasis: '#1f883d'
  success-subtle: '#dafbe1'
  success-dark-fg: '#3fb950'
  danger-fg: '#cf222e'
  danger-emphasis: '#cf222e'
  danger-subtle: '#ffebe9'
  danger-dark-fg: '#f85149'
  attention-fg: '#9a6700'
  attention-subtle: '#fff8c5'
  attention-dark-fg: '#d29922'
typography:
  body-md:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0px
  body-sm:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0px
  heading-section:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: 0px
  code-inline:
    fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: 0px
rounded:
  none: 0px
  sm: 3px
  md: 6px
  lg: 8px
  pill: 9999px
spacing:
  none: 0px
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
components:
  telemetry-box:
    backgroundColor: '{colors.canvas-default}'
    textColor: '{colors.fg-default}'
    typography: '{typography.body-md}'
    rounded: '{rounded.md}'
    padding: '{spacing.md}'
  status-hud-pill:
    backgroundColor: '{colors.success-subtle}'
    textColor: '{colors.success-fg}'
    typography: '{typography.code-inline}'
    rounded: '{rounded.pill}'
    padding: '{spacing.xxs}'
---

# AstrBot Resource Monitor 质感设计系统规范 (`DESIGN.md`)

本文档是 [`astrbot-resource-monitor`](file:///D:/Projects/CyberNova2333/git-repos/astrbot-resource-monitor) 的设计系统规范。针对资源线路可用性探针（检查清单、Range 响应、分块 MD5、热更包与 TLS 证书）与告警渲染，基于 GitHub Primer 功能原语融入**硬件遥测座舱质感（Hardware Telemetry HUD Materiality）**，定义机器人富文本消息卡片、管理渲染器与文档站交互规范。

---

## 1. 核心设计哲学与物理质感

1. **硬件遥测指示灯（Physical Telemetry Indicators）**：
   - 探针巡检状态具备发光 LED 呼吸质感：健康（荧光绿 `#3fb950`）、降级/重试（琥珀黄 `#d29922`）、断流/校验失败（警报红 `#f85149`），带有微透镜物理光晕（`0 0 6px currentColor`）。
2. **仪表盘沉槽导轨（Recessed Gauge Tracks）**：
   - 响应时间与分块校验进度使用物理内凹沉槽：底槽带有 `inset 0 1px 2px rgba(0, 0, 0, 0.25)` 深度阴影，填充条具备顶端斜角反光。
3. **触觉物理按压（Tactile Kinematics）**：
   - 消息内交互按钮与控制面板支持实体按压手感（`:hover` `translateY(-0.5px)`，`:active` `translateY(0.5px) scale(0.99)` + `inset 0 2px 4px rgba(0, 0, 0, 0.2)`）。

---

## 2. 调色板与语义 Token

### 2.1 W3C `$value/$type` Token 注册表

| Primer 功能 Token | Light `$value` | Dark `$value` | 遥测映射与用途 |
| :--- | :--- | :--- | :--- |
| `canvas.default` | `#ffffff` | `#0d1117` | 监控卡片白底/深空黑底 |
| `canvas.inset` | `#f6f8fa` | `#010409` | 遥测座舱仪表底板、代码块内凹槽 |
| `canvas.subtle` | `#f6f8fa` | `#161b22` | 探针列表项底色、统计表头 |
| `fg.default` | `#1f2328` | `#f0f6fc` | 线路名称、校验结果正文 |
| `fg.muted` | `#57606a` | `#8b949e` | 响应时间（ms）、时间戳、探针周期 |
| `border.default` | `#d0d7de` | `#30363d` | 容器物理边框（1px solid） |
| `success.fg` | `#1a7f37` | `#3fb950` | 线路恢复通知、MD5 严格一致、证书有效 |
| `attention.fg` | `#9a6700` | `#d29922` | HTTP 200 但内容疑似被劫持预警、慢速线路 |
| `danger.fg` | `#cf222e` | `#f85149` | 线路彻底故障、Range 校验失败、证书过期告警 |

---

## 3. 字体栈与空间规范

- **工程字体栈（`--font-sans`）**：`-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif`
- **等宽数据字体（`--font-mono`）**：`ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace`
- **排版要求**：正文 `14px`，线路延迟与哈希指纹强制使用 `12px` 等宽字体与 `font-variant-numeric: tabular-nums`。

---

## 4. 核心组件与通知边界约束

1. **只观察不越权**：插件坚决只做“观察与通知”，不在渲染层与逻辑层擅自切换线路或篡改配置。
2. **“HTTP 200 假成功”防伪标识**：对于 HTTP 状态码为 200 但 Range/MD5 校验不符的异常，强制使用加粗红底警示卡，防止静默污染。
3. **富文本通知卡片**：消息采用 Primer Box 结构，具备明显的 1px 描边与顶边微高光，保证在各种 IM 客户端下具备清晰的可读性与仪式感。
