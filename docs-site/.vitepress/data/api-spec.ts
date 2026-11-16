import type { ApiCatalogSpec } from './api-types'

export const apiSpecZh: ApiCatalogSpec = {
  project: 'AstrBot Resource Monitor · 探针、指令与扩展参考',
  subtitle:
    '覆盖 10 项分发线路含量级探针（P0/P1/P2）、公网 SSRF/重定向/64 MiB 安全防线、8 条群内 /线路 指令，以及 Source / HttpClient 离线可测扩展接口。',
  environments: [
    { label: 'AstrBot 插件目录', value: 'data/plugins/astrbot_plugin_resource_watch' },
    { label: '离线单元测试库', value: 'python3 -m unittest discover -s tests -t .' },
  ],
  searchPlaceholder: '搜索探针、P0/P1、/线路、64 MiB、validate_public_url…',
  emptyText: '没有找到匹配的探针、指令或接口。',
  labels: {
    allGroups: '全部',
    canDo: '✅ 能做到',
    cannotDo: '⛔ 明确限制 / 拒绝条件',
    params: '参数、阈值与安全边界',
    paramName: '字段 / 指令',
    paramLocation: '作用域',
    paramType: '类型',
    paramRequired: '要求',
    paramDesc: '说明与硬上限',
    responses: '判定输出与抑制行为',
    examples: '标准调用 / 配置示例',
    responseSample: '典型返回 / 状态快照示例',
    copy: '复制',
    copied: '已复制',
    noParams: '无需额外调用参数。',
    required: '必填',
    optional: '可选',
    deepDocs: '查看探针与安全护栏详解',
    totalItems: '项接口/探针',
    envLabel: '运行上下文',
    mobilePicker: '切换探针或组件',
    defaultLabel: '默认',
    plainIndexToggle: '纯文本检索与打印索引（Ctrl+K 站内搜索定位）',
  },
  groups: [
    { id: 'probes', title: '10 项内容与协议探针' },
    { id: 'commands-spi', title: '/线路指令、安全闸与 SPI' },
  ],
  items: [
    {
      id: 'probes-config-manifest',
      group: 'probes',
      kind: 'HOOK',
      title: '配置发现与清单一致性探针 (配置源 / 合理性 / 清单 / 一致性 / 版本)',
      signature: 'P0 配置源可达性 · P0/P1 线上配置合理性 · P1 清单可达性 · 线路一致性 · 版本 json',
      auth: 'PublicResolver 公网 pinning + NO_CACHE',
      stability: '快巡检主线 (300s)',
      summary:
        '拒绝「HTTP 200 却悄悄降级」的假健康：验证 endpoint 返回合法 mirrors[]、防范启用线路骤降 >=50% 或版本回退、校验 manifest.json 每块 32 位 MD5 及多数共识（count * 2 > total）。',
      relatedLink: '/docs/contracts',
      relatedLabel: '查看 P0/P1 与 unknown=True 判据',
      capabilities: [
        '触发 KEY_ENTRY（配置源失败）自动抑制下游合理性/清单/一致性告警；单镜像 manifest 失败自动抑制该镜像子节点告警',
        '仅当未超龄缓存快照可用且主入口失联时给出 unknown=True 排查线索，绝不代判全绿',
      ],
      limitations: [
        '严格只读观测：绝不自动切换线上 CDN 路由或修改上游配置，也不采集宿主机 CPU / 内存指标',
        '1:1 平票或缺少多数派一致时不标误报 FAIL，改为标 unknown=True 并暂停基准对比；仓库零内置默认地址',
      ],
      params: [
        { name: 'entry_url / mirrors', location: 'config', type: 'public HTTP(S) URL[]', required: true, description: '启动至少配一种；严格禁 localhost、私网/保留 IP（含 IPv4 映射 IPv6）与 trust_env。' },
      ],
      responses: [
        { status: 'ProbeResult (ok / fail / unknown=True)', tone: 'ok', summary: '经 AlertState M-of-N 滑动窗口收敛并先落盘 watch-state.json 后投递' },
      ],
      examples: [
        {
          label: 'endpoint discovery JSON 结构',
          lang: 'json',
          code: `{
  "mirrors": [{ "base": "https://cdn-a.example.test/" }],
  "settings": { "min_speed_kbps": 128 },
  "client": { "version": "1.2.0" },
  "watch": { "version_files": ["version.json"], "packages": { "hotfix": "hot.zip" } }
}`,
        },
      ],
    },
    {
      id: 'probes-range-md5-tls',
      group: 'probes',
      kind: 'HOOK',
      title: 'HTTP Range 分片、MD5 轮转、热更整包与 TLS 到期',
      signature: 'P1 Range 支持 · P1 块内容校验 · P2 线路速率 · P1 热更整包 · P2/P0 证书有效期',
      auth: '64 MiB 缓冲上限 + 不穿 Edge 缓存',
      stability: '快慢双锁隔离',
      summary:
        '不加 Cache-Control: no-cache 直接沿 CDN 真实用户路径拉取轮转 (mirror, file, chunk) 验证 HTTP 206 与 MD5（推进 7 天覆盖游标），每天检查 TLS 证书 notAfter 并在 <14d/<3d 分级告警。',
      relatedLink: '/docs/contracts',
      relatedLabel: '查看缓冲上限与速率规则',
      capabilities: [
        '快巡检（默认 300s）与慢巡检（默认 3600s）各自持有独立异步锁；慢热更包检验完成前比对快照一致性以防配置漂移污染计时器',
        'stream digest() 严格上限 meta.size + 1 MiB 与至少 1800s 流超时，超限立刻 abort',
      ],
      limitations: [
        'HttpClient.fetch 缓冲上限锁定 min(64 MiB, max_body_bytes)，不可被远程清单私自调高；超限标 unknown=True 且不推进 7 天覆盖',
        '群聊手动命令固定强制 allow_heavy=False，跳过百 MB 热更整包下载防复读刷爆源站',
      ],
      params: [
        { name: 'MAX_BUFFER_BYTES', location: 'config', type: '64 MiB', required: true, description: '硬性内存分块防护上限；返回 HTTP 200 无视 Range 直接判 P1 失败。' },
      ],
      responses: [
        { status: '206 Partial Content + MD5 Match', tone: 'ok', summary: '校验通过后更新 7 天轮转游标' },
        { status: 'TLS <14d P2 / <3d P0', tone: 'warn', summary: '逐一检验 getaddrinfo 返回的全部公网 IP 证书有效期' },
      ],
      examples: [
        { label: '离线安全与单测检验', lang: 'sh', code: `python3 -m unittest discover -s tests -t . -v\npython3 tools/check-no-endpoints.py --verbose` },
      ],
    },
    {
      id: 'commands-spi-security',
      group: 'commands-spi',
      kind: 'CLI',
      title: '8 条群内 /线路 运维指令、SSRF 防线与 Source/HttpClient SPI',
      signature: '/线路 状态|测|配置|静音|取消静音|覆盖率|通知|确认 · Source · HttpClient',
      auth: 'notify.sessions 白名单 + CommandGate + 管理员确认',
      stability: '扩展与运维接口',
      summary:
        '面向会话白名单提供中英双别名 /线路 指令与 QQ 官方平台 /线路 通知 -> /线路 确认 管理员核销闭环；底层通过抽象 Source 与 HttpClient 支持零外网 FakeClient 测试与扩展数据源。',
      relatedLink: '/docs/configuration',
      relatedLabel: '查看参数矩阵与 QQ 官方接线',
      capabilities: [
        'watch/render.py safe() 将 [CQ:/[at: 转为全角［tag：并转义 @全体成员/@everyone，防机器人出群伪造注入',
        '_flush_outbox 发送前对每个接收者再次核验 _discard_stale 防止投递期间恢复仍发出过时告警',
      ],
      limitations: [
        '仅响应白名单会话；测 与 配置 共用全局 60s 冷却且禁止整包重下载；/线路 确认 始终只限管理员',
        '刻意不做长期历史 SLA 图表，仅持久化 watch-state.json 当前活动告警、7 天覆盖游标与待发队列',
      ],
      params: [
        { name: 'RESOURCE_WATCH_CONFIG / watch-state.json', location: 'config', type: 'JSON config & state', required: false, description: 'WebUI 有效配置优先于环境变量；目录写入失败即暂停发送保留队列不丢状态。' },
      ],
      responses: [
        { status: 'Sanitized Chat Reply / Acked', tone: 'ok', summary: '单字段 ≤ 160 字符、总消息 ≤ 3000 字符；QQ 官方等待管理员核销' },
      ],
      examples: [
        {
          label: '群内常用运维指令',
          lang: 'text',
          code: `/线路 状态
/线路 测 cdn-a
/线路 静音 30m
/线路 通知
/线路 确认`,
        },
      ],
    },
  ],
}

export const apiSpecEn: ApiCatalogSpec = {
  project: 'AstrBot Resource Monitor · Probes, Commands & SPI',
  subtitle:
    'Interactive specification covering 10 content-verified distribution probes (P0/P1/P2), SSRF/64 MiB guardrails, 8 `/线路` chat commands, and pluggable Source/HttpClient SPIs.',
  environments: [
    { label: 'AstrBot Plugin Directory', value: 'data/plugins/astrbot_plugin_resource_watch' },
    { label: 'Offline Unit Suite', value: 'python3 -m unittest discover -s tests -t .' },
  ],
  searchPlaceholder: 'Filter probes, P0/P1, /线路, 64 MiB, validate_public_url…',
  emptyText: 'No matching probe, command, or SPI found.',
  labels: {
    allGroups: 'All',
    canDo: '✅ Capabilities',
    cannotDo: '⛔ Explicit Limits / Rejections',
    params: 'Settings, Limits & Security Gates',
    paramName: 'Symbol / Command',
    paramLocation: 'Scope',
    paramType: 'Type',
    paramRequired: 'Rule',
    paramDesc: 'Description & Hard Caps',
    responses: 'Verdicts, Suppression & Delivery',
    examples: 'Standard Usage / Schema',
    responseSample: 'Sample Snapshot',
    copy: 'Copy',
    copied: 'Copied',
    noParams: 'No additional arguments required.',
    required: 'Required',
    optional: 'Optional',
    deepDocs: 'Open probes & security docs',
    totalItems: 'components',
    envLabel: 'Runtime Context',
    mobilePicker: 'Select Component',
    defaultLabel: 'Default',
    plainIndexToggle: 'Plaintext Search & Print Index (Ctrl+K Target)',
  },
  groups: [
    { id: 'probes', title: '10 Content & Protocol Probes' },
    { id: 'commands-spi', title: '/线路 Commands, Gates & SPI' },
  ],
  items: [
    {
      id: 'probes-config-manifest',
      group: 'probes',
      kind: 'HOOK',
      title: 'Endpoint Discovery, Config Sanity, Manifest, Consensus & Version Probes',
      signature: 'P0 Discovery · P0/P1 Sanity · P1 Manifest · Consensus · Version JSON',
      auth: 'PublicResolver IP Pinning + NO_CACHE',
      stability: 'Fast Lock Loop (300s)',
      summary: 'Detects corrupt endpoints, >=50% mirror drops, version regressions, invalid 32-hex manifest MD5s, and strict majority splits (`count * 2 > total`).',
      relatedLink: '/en/docs/contracts',
      relatedLabel: 'Inspect P0/P1 & unknown=True rules',
      capabilities: ['Two-tier suppress_key filtering silences downstream noise automatically when primary entry fails'],
      limitations: ['Strictly read-only (never alters upstream configs or monitors host CPU/RAM); lacks built-in default endpoints'],
      params: [{ name: 'entry_url / mirrors', location: 'config', type: 'public HTTP(S) URL[]', required: true, description: 'Rejects localhost, loopback/private/reserved IPs, redirects >5 hops, cookies, and trust_env proxies.' }],
      responses: [{ status: 'ProbeResult (ok / fail / unknown)', tone: 'ok', summary: 'Debounced via M-of-N windows and saved to watch-state.json before delivery' }],
      examples: [{ label: 'Discovery JSON', lang: 'json', code: `{ "mirrors": [{ "base": "https://cdn-a.example.test/" }], "settings": { "min_speed_kbps": 128 }, "client": { "version": "1.2.0" } }` }],
    },
    {
      id: 'probes-range-md5-tls',
      group: 'probes',
      kind: 'HOOK',
      title: 'HTTP Range, MD5 Chunk Rotation, Hot Packages & TLS Expiry',
      signature: 'P1 Range · P1 Chunk MD5 · P2 Speed · P1 Hot Package · P2/P0 TLS Expiry',
      auth: '64 MiB Buffer Ceiling + Edge Cache Path',
      stability: 'Dual-Lock Isolation',
      summary: 'Verifies real CDN edge slices (HTTP 206 + 7-day rotating MD5 cursor), streaming package digests, and daily per-IP TLS notAfter (<14d P2 / <3d P0).',
      relatedLink: '/en/docs/contracts',
      relatedLabel: 'Inspect 64 MiB & Range boundaries',
      capabilities: ['Separate fast/slow async locks + snapshot matching prevent mid-download scheduler state corruption'],
      limitations: ['Caps fetch buffer at 64 MiB; manual chat probes force allow_heavy=False skipping multi-hundred-MB hot archives'],
      params: [{ name: 'MAX_BUFFER_BYTES', location: 'config', type: '64 MiB', required: true, description: 'Immutable ceiling; returning 200 without 206 Partial Content fails P1.' }],
      responses: [{ status: '206 + MD5 Match / TLS Check', tone: 'ok', summary: 'Advances 7-day chunk coverage cursor only on verified non-skipped slices' }],
      examples: [{ label: 'Offline Tests & Guard', lang: 'sh', code: `python3 -m unittest discover -s tests -t . -v\npython3 tools/check-no-endpoints.py --verbose` }],
    },
    {
      id: 'commands-spi-security',
      group: 'commands-spi',
      kind: 'CLI',
      title: '8 Chat Commands (/线路), Output Guard & Pluggable SPIs',
      signature: '/线路 状态|test|config|mute|unmute|coverage|notifications|ack · Source · HttpClient',
      auth: 'Session Allowlist + CommandGate + Admin Ack',
      stability: 'Commands & SPI',
      summary: 'Bilingual chat controls, render.safe() mention neutralization, per-recipient outbox re-validation, and offline FakeClient SPI hooks.',
      relatedLink: '/en/docs/configuration',
      relatedLabel: 'View config & QQ Official guide',
      capabilities: ['Custom Source subclasses & HttpClient mocks work cleanly without modifying probes or AlertState'],
      limitations: ['No long-term SLA reports; /线路 确认 (ack) always requires admin privileges and shared heavy cooldown (60s)'],
      params: [{ name: 'RESOURCE_WATCH_CONFIG / watch-state.json', location: 'config', type: 'JSON', required: false, description: 'Valid WebUI config overrides env var; atomic state persistence prevents duplicate bursts.' }],
      responses: [{ status: 'Sanitized Reply (<=3000 chars)', tone: 'ok', summary: 'Fullwidth escapes block bot command/mention injection' }],
      examples: [{ label: 'Chat Commands', lang: 'text', code: `/线路 status\n/线路 test cdn-a\n/线路 mute 30m\n/线路 notifications\n/线路 ack` }],
    },
  ],
}
