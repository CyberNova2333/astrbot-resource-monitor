---
title: Configuration Guide
description: Plugin configuration keys, alert thresholds, and notification targets.
---

::: warning AI Translation Notice
This document was translated by an AI language model. In case of any discrepancies or ambiguities, please refer to the [original Chinese documentation](/docs/configuration) as the authoritative reference.
:::

# Configuration Guide

### Primary Configuration

```json
{
  "check_interval_seconds": 60,
  "alert_cooldown_minutes": 15,
  "thresholds": {
    "cpu_percent": 85.0,
    "memory_percent": 90.0,
    "disk_percent": 92.0
  },
  "enable_visual_cards": true
}
```

---

## Production Recommendations

1. **Environment Variable Protection**: Never commit real API keys or sensitive credentials into Git repositories.
2. **Graceful Shutdown & Timeouts**: Set appropriate timeout constraints on long-running processes to prevent orphan executions.
3. **Continuous Monitoring**: Combine console logs and health telemetry to monitor service uptime and operational status.
