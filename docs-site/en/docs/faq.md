---
title: FAQ & Troubleshooting
description: Frequently asked questions and troubleshooting tips for AstrBot Resource Monitor.
---

::: warning AI Translation Notice
This document was translated by an AI language model. In case of any discrepancies or ambiguities, please refer to the [original Chinese documentation](/docs/faq) as the authoritative reference.
:::

# FAQ & Troubleshooting

Common questions and answers regarding daily usage and integration:

### Q: Does this plugin require root / sudo permissions?

**A**: No. Standard user privileges are sufficient to query procfs and system statistics.

### Q: How to change the notification frequency?

**A**: Adjust `alert_cooldown_minutes` in the plugin configuration to suppress repeat notifications during prolonged spikes.


---

## General Troubleshooting Steps

1. **Verify Runtime Versions**: Ensure Node.js, Python, Rust, or browser versions meet minimum compatibility requirements.
2. **Check Diagnostic Logs**: Review console output and error logs for informative stack traces and line numbers.
3. **Submit Issue Feedback**: If you discover an underlying bug, please open an issue on the GitHub repository with a reproducible test case.
