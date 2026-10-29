# 安全说明 / Security

<!-- repo-maintenance:begin -->
## 本地提交与推送检查 / Local commit and push checks

安全钩子只在本机运行。`pre-commit` 检查即将提交的 Git 暂存对象；`commit-msg` 检查标题与信息中的常见凭证形态；`pre-push` 按 Git 提供的引用范围检查新增历史，包含最终版本已经删除的中间提交。不会向外上传源码或扫描结果，也不会自动修改文件。

The hooks run offline. They scan staged objects, commit messages and the commits introduced by a push, including intermediate commits. They do not upload source or results and do not modify application files.

检查覆盖私钥头、常见服务令牌、真实环境配置路径、敏感凭据文件名与本机设计文稿文件名。环境模板可以提交；真实配置、私钥和开发者本机文稿应留在版本控制之外。诊断只显示规则、路径和行号，不回显疑似凭证。超过 8 MiB 的对象只检查路径并明确提示未扫描内容；大型资产继续遵循原有 Git LFS 和专用检查规则。此检查不能识别所有凭证形态，也不替代代码审查、依赖审计和项目已有安全钩子。

Coverage includes private-key headers, common token formats and sensitive paths. Keep real local configuration, private keys and local-only design manuscripts out of version control. Diagnostics show rule identifiers and locations, never the matched value. Blobs larger than 8 MiB receive path checks and an explicit content-scan notice; retain existing LFS and asset checks. These checks do not detect every secret and do not replace review, dependency audits or existing protections.

确认为可公开测试夹具的内容，可以在 `.repo-security-allowlist.json` 登记仓库相对路径、文件完整内容的 `sha256` 和解释用途的 `reason`。不支持通配符；内容变化后必须重新审阅。例外须和文件一起暂存；推送时按每条提交里的例外清单检查，未暂存的工作区清单不能放宽规则。

Public test fixtures may be reviewed using an exact-path, exact-content SHA-256 entry with a reason in `.repo-security-allowlist.json`. Wildcards are unsupported. Stage the exception with the fixture. The check reads exceptions from the index or the relevant pushed commit, never from unstaged working files.

```json
{
  "tests/fixtures/public-example.txt": {
    "sha256": "<64 lowercase hexadecimal characters>",
    "reason": "Reviewed public fixture; explain why no credential is usable"
  }
}
```

发现泄露时先撤销或轮换凭据，再评估受影响的历史、制品和日志；删除最新文件无法撤回旧提交。报告只包含必要的复现步骤、影响范围和脱敏位置。使用仓库已有私密联系渠道向维护者报告；未配置私密渠道时先私下建立联系，不在公开 Issue 中粘贴凭证、私密数据或可直接利用的细节。

Revoke or rotate exposed credentials first, then assess history, artifacts and logs. Removing the latest file does not remove older commits. Use an existing private reporting channel; establish a private contact if none is documented, and keep credentials and private data out of public issues.
<!-- repo-maintenance:end -->
