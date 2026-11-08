---
title: 配置与使用指南
description: AstrBot 监控插件 的参数配置详解、典型使用场景与最佳实践
---

# 配置与使用指南

### 配置选项 (config.json)

```json
{
  "probe_interval_seconds": 60,
  "alert_thresholds": {
    "cpu_percent": 85,
    "memory_percent": 90,
    "disk_percent": 95
  },
  "alert_channels": ["webhook", "bot_admin"],
  "allowed_hosts": ["example.test", "localhost"]
}
```

### 守卫铁律 (check-no-endpoints)

- 绝不入库任何真实生产地址、IP、私钥或 Token；
- 占位符统一使用 RFC 6761 保留域名 `example.test`，确保示例配置绝不会向真实主机发送流量。

---

## 生产部署建议

1. **环境变量保护**：切勿将包含真实密钥或 Token 的配置提交至版本库；
2. **优雅停机与超时**：建议将关键长任务的超时时限设置为合理范围，避免僵尸进程驻留；
3. **日志监控**：结合控制台输出建立定期检查机制，捕获潜在异常。
