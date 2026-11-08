# AstrBot Resource Monitor

[中文完整说明](README.md) · [Chinese source guide](repo-docs/README.md)

An AstrBot plugin that checks resource distribution routes against client-facing content rules and reports confirmed failures and recoveries. HTTP 200 alone is insufficient: manifest, Range, block digest, package and certificate checks inspect whether the content is usable. The plugin observes and notifies; it does not repair configuration or switch routes.

## Install and configure

Place the complete checkout under AstrBot's `data/plugins/` and install `requirements.txt` in that environment. The runtime dependency requires Python 3.10+. Keep both `main.py` and `watch/`; imports are package-relative.

Configure an entry document or mirror source, notification sessions and command permissions through the plugin settings. The schema is in `_conf_schema.json`; `config.example.json` uses neutral examples. Actual endpoints, credentials and session identifiers belong only in deployment configuration. Current route lists, file manifests and client thresholds come from the online source; cached data can assist diagnosis but cannot declare current health.

## Notifications and commands

Use `/线路 状态` for status, `/线路 测 <线路名>` for a bounded manual check, and `/线路 静音 30m` / `/线路 取消静音` for maintenance. `/线路 覆盖率` reports verified sampling coverage.

For QQ official adapters, use the real platform instance metadata and the deployment's exact UMO, not an ordinary account/group number. Successful send calls only mark an attempt as submitted; the pending item remains available through `/线路 通知`. An administrator must view it and then use `/线路 确认` in the same session. Viewing does not clear it; after restart it must be viewed again. Output uses plain text, omits links and downgrades mass mentions.

Failures, recovery, deduplication and mute windows are persisted. The sender checks stale alerts and mute state before each recipient. Persistence failure retains pending work; platform submission and local persistence are not an exactly-once delivery transaction.

## Verification and limits

```sh
python -m unittest discover -s tests -t .
python tools/check-no-endpoints.py
python -m compileall -q watch main.py
```

Tests use fake HTTP and framework adapters. They do not prove real QQ delivery, permissions or quota. This documentation sync inspected tests but did not run them. Only public network targets are supported; internal-network monitoring is outside the current boundary.

## License

[GPLv3](LICENSE). Read the Chinese README, existing probe reference and Agent rules before changing checks or publishing examples. Real addresses, session IDs and credentials must never enter the repository.

## Documentation site

The [Chinese source guide](repo-docs/README.md) follows one implemented workflow, then links to a code map and evidence audit. It does not claim complete architecture coverage.

```sh
pnpm --dir docs-site install --frozen-lockfile
pnpm --dir docs-site run docs:dev -- --host 127.0.0.1
pnpm --dir docs-site run docs:build
```

The documentation site uses the default VitePress theme, with dependencies installed separately from the application. Output defaults to `docs-site/.vitepress/dist/`; append `-- --outDir <external-absolute-directory>` for an isolated build. Markdown remains in `repo-docs/` and is included by the site. Repository source links are shown as exact paths; source files and local resources are not published.
