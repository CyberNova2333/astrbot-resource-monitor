#!/usr/bin/env python3
"""Incrementally sync newly discovered Git contributors and AI tools into ASSETS_LICENSES.md.

Usage:
    python3 sync_assets_licenses.py github [--check] [--dry-run] [--repo PATH]
    python3 sync_assets_licenses.py mirror [--check] [--dry-run] [--repo PATH]
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, quote_plus, urlsplit

GH_NOREPLY_RE = re.compile(
    r"^(?:(\d+)\+)?([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(\[bot\])?@users\.noreply\.github\.com$",
    re.I,
)
MIRROR_NOREPLY_RE = re.compile(r"^[^+]+\+([A-Za-z0-9_.-]+)@noreply\.[A-Za-z0-9.-]+$", re.I)
# Allow common RFC local-part chars & arbitrary non-whitespace domain labels (incl. IDN / IP / single-char TLD)
EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+(?:\[bot\])?@[^\s`<>()|\"',;]+\.[^\s`<>()|\"',;]+")
GH_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9-]+)", re.I)
MIRROR_URL_RE = re.compile(r"https?://[^/\s`]+/u/([A-Za-z0-9_.-]+)", re.I)
TRAILER_RE = re.compile(r"^\s*([^<>]+?)\s*<([^<>@\s]+@[^<>\s]+)>\s*$")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
ROLE_SUFFIX_RE = re.compile(
    r"(?:（(?:Git 贡献者|项目维护者|上游基线历史作者|AI 编程辅助工具|[^）]*Git 角色：)[^）]*）|\((?:Git contributor|Project maintainer|AI coding assistant)[^)]*\))\s*$",
    re.I,
)
URL_USERINFO_RE = re.compile(r"(https?://)([^/\s@]+)@", re.I)

AI_HANDLE_SUFFIXES = ("-assist", "-agent", "-copilot")
AI_EXACT_HANDLES = ("copilot",)
AI_VENDOR_BRANDS = {
    "anthropic",
    "openai",
    "moonshot",
    "kimi",
    "deepseek",
    "codebuddy",
    "cursor",
}
AI_CANONICAL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgemini-code-assist\b", re.I), "gemini-code-assist"),
    (re.compile(r"\bclaude\b", re.I), "Claude"),
    (re.compile(r"\bcodex\b", re.I), "Codex"),
    (re.compile(r"\bcodebuddy\b", re.I), "CodeBuddy"),
    (re.compile(r"\bdeepseek\b", re.I), "DeepSeek"),
    (re.compile(r"\bkimi\b", re.I), "Kimi"),
    (re.compile(r"\bantigravity\b", re.I), "gemini-code-assist"),
    (re.compile(r"\bgithub\s+copilot\b", re.I), "GitHub Copilot"),
    (re.compile(r"\bcopilot\b", re.I), "Copilot"),
    (re.compile(r"\bgoogle\s+gemini\b", re.I), "Google Gemini"),
    (re.compile(r"\bgemini\b", re.I), "Gemini"),
    (re.compile(r"\bcursor\b", re.I), "Cursor"),
]
ROLE_ORDER = ("Committer", "Author", "Co-authored-by")
CONSENT_NO = "[附加条款：未发表意见]"


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def redact_url_userinfo(text: str) -> str:
    return URL_USERINFO_RE.sub(r"\1***@", text)


def escape_md_cell(text: str) -> str:
    cleaned = text.replace("\r", " ").replace("\n", " ").replace("\u2028", " ").replace("\u2029", " ")
    cleaned = cleaned.replace("\\", "\\\\").replace("|", "\\|")
    cleaned = cleaned.replace("`", "'").replace("<", "").replace(">", "").replace("[", "").replace("]", "")
    return normalize_space(cleaned)


def unescape_md_cell(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in ("\\", "|"):
            out.append(text[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_md_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    # 统计结尾 | 前连续反斜杠数目，仅偶数个反斜杠后的 | 才是真实行末闭合分隔符
    if s.endswith("|"):
        bs = 0
        j = len(s) - 2
        while j >= 0 and s[j] == "\\":
            bs += 1
            j -= 1
        if bs % 2 == 0:
            s = s[:-1]

    cells: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(s[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append(unescape_md_cell("".join(buf)).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append(unescape_md_cell("".join(buf)).strip())
    return cells


def extract_mirror_user(email: str) -> str | None:
    m = MIRROR_NOREPLY_RE.match(email.strip())
    return m.group(1) if m else None


def is_ai_gh_handle(base_handle: str) -> bool:
    hl = base_handle.lower()
    if hl in AI_EXACT_HANDLES or hl.endswith(AI_HANDLE_SUFFIXES):
        return True
    return any(pat.search(hl) for pat, _ in AI_CANONICAL_RULES)


def is_excluded_bot(name: str, email: str, role: str) -> bool:
    nl = normalize_space(name).lower()
    el = email.strip().lower()
    local, _, domain = el.partition("@")
    if not domain or "." not in domain or domain.endswith(".local"):
        return True
    if nl.endswith("[bot]") or el.endswith("[bot]@users.noreply.github.com"):
        m_gh = GH_NOREPLY_RE.match(el)
        base_handle = m_gh.group(2).lower() if m_gh else re.sub(r"\[bot\]$", "", local).lower()
        if not is_ai_gh_handle(base_handle):
            return True
    if nl == "mirror-bot" or nl.endswith("-bot"):
        return True
    if local in {"actions", "bot", "ci"} or "autobot" in nl or "流水线" in nl:
        return True
    if local == "noreply" and (domain.startswith("github.") or "web-flow." in domain or domain == "example.test"):
        return True
    mirror_noreply_dom = os.environ.get("MIRROR_NOREPLY_DOMAIN", "").strip().lower()
    if (
        local == "noreply"
        and ((mirror_noreply_dom and domain.startswith(mirror_noreply_dom)) or domain.endswith(".cool"))
        and role != "Co-authored-by"
    ):
        return True
    return False


def is_agent_record(name: str, email: str, role: str) -> bool:
    nl = normalize_space(name).lower()
    el = email.strip().lower()
    local, _, domain = el.partition("@")
    m_gh = GH_NOREPLY_RE.match(el)
    if m_gh:
        return is_ai_gh_handle(m_gh.group(2))
    if extract_mirror_user(el):
        return False
    domain_brand = domain.split(".", 1)[0] if domain else ""
    has_known_brand = any(pat.search(nl) for pat, _ in AI_CANONICAL_RULES)
    if domain_brand in AI_VENDOR_BRANDS and local in {"noreply", "no-reply", "ai", "agent", "assistant", domain_brand}:
        return True
    if local in {"ai", "agent", "assistant"} and (has_known_brand or domain_brand in AI_VENDOR_BRANDS):
        return True
    if has_known_brand and (
        local in {"noreply", "no-reply", "codebuddy", "copilot"} or domain_brand in AI_VENDOR_BRANDS
    ):
        return True
    return False


def canonical_agent_name(raw_name: str) -> str:
    cleaned = normalize_space(re.sub(r"\[bot\]$", "", raw_name, flags=re.I))
    for pattern, canonical in AI_CANONICAL_RULES:
        if pattern.search(cleaned):
            return canonical
    return cleaned or raw_name.strip()


def pick_agent_email(canon_name: str, email_counts: Counter[str]) -> str:
    cl = canon_name.lower()

    def sort_key(item: tuple[str, int]) -> tuple[int, int, int, int, str]:
        em, count = item
        local, _, domain = em.partition("@")
        m_gh = GH_NOREPLY_RE.match(em)
        if m_gh:
            return (0, 1 if m_gh.group(3) else 0, -count, 0, em)
        is_mirror_proxy = domain.startswith("noreply.") or domain.endswith(".cool")
        dom_match = 0 if domain.startswith(cl.replace(" ", "") + ".") else 1
        is_noreply = 0 if local == "noreply" else 1
        return (1 if not is_mirror_proxy else 2, -count, is_noreply, dom_match, em)

    return sorted(email_counts.items(), key=sort_key)[0][0]


def sanitize_http_origin(raw_url: str) -> str:
    raw = (raw_url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        port_num = parts.port
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return ""
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{port_num}" if port_num is not None else ""
    return f"{parts.scheme.lower()}://{host}{port}"


def resolve_mirror_base(repo: Path | None = None) -> str:
    cleaned = sanitize_http_origin(os.environ.get("MIRROR_WEB_ENDPOINT", ""))
    if cleaned:
        return cleaned
    cmd = ["git"] + (["-C", str(repo)] if repo else []) + ["remote", "get-url", "origin"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return sanitize_http_origin(res.stdout.strip()) if res.returncode == 0 else ""


def resolve_repo_owner(repo: Path) -> str:
    meta_path = repo / "meta.json"
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text("utf-8"))
            m = re.match(r"^https?://github\.com/([^/]+)/", str(data.get("repository", "")))
            if m:
                return m.group(1)
            links = data.get("links")
            if isinstance(links, dict):
                m = re.match(r"^https?://github\.com/([^/]+)/", str(links.get("github", "")))
                if m:
                    return m.group(1)
        except (OSError, ValueError):
            pass
    for remote in ("github", "origin"):
        res = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", remote],
            capture_output=True,
            text=True,
            timeout=15,
        )
        m = re.search(r"github\.com[:/]([^/]+)/", res.stdout.strip())
        if m:
            return m.group(1)
    return ""


def email_sort_key(email: str) -> tuple[int, str]:
    el = email.lower()
    m = GH_NOREPLY_RE.match(el)
    if m:
        return (0 if m.group(1) else 1, el)
    if extract_mirror_user(el):
        return (2, el)
    return (3, el)


def name_sort_key(name: str) -> tuple[int, int, str]:
    has_upper = any(c.isupper() for c in name)
    return (0 if has_upper else 1, -len(name), name.lower())


def is_git_repo(repo: Path) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            timeout=15,
        ).returncode
        == 0
    )


def has_head_commit(repo: Path) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"],
            capture_output=True,
            timeout=15,
        ).returncode
        == 0
    )


def collect_git_identities(
    repo: Path, *, platform: str = "github", check_only: bool = False, dry_run: bool = False
) -> tuple[list[dict], list[dict], dict[str, int]]:
    is_shallow = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"], text=True, timeout=15
    ).strip()
    if is_shallow == "true":
        if check_only or dry_run:
            log("警告：当前仓库为 shallow clone，未拉取完整历史；检查结果可能不完整。")
        else:
            unshallow = subprocess.run(
                ["git", "-C", str(repo), "fetch", "--unshallow", "--quiet"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if unshallow.returncode != 0:
                raise RuntimeError(f"git fetch --unshallow 失败：{redact_url_userinfo(unshallow.stderr.strip())}")

    fmt = "%H%x00%s%x00%an%x00%ae%x00%cn%x00%ce%x00%(trailers:key=Co-authored-by,valueonly,separator=%x1f)%x1e"
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "log", "HEAD", "--reverse", f"--format={fmt}"],
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    mirror_base = resolve_mirror_base(repo)
    repo_owner = resolve_repo_owner(repo)
    owner_lower = repo_owner.lower() if repo_owner else ""

    human_by_pair: dict[tuple[str, str], dict] = {}
    agents: dict[str, dict] = {}
    stats = {"commits": 0, "excluded_bots": 0, "skipped_bot_commits": 0}

    def record(sha: str, name: str, email: str, role: str) -> None:
        name = normalize_space(name)
        email = email.strip()
        if not name or not email:
            return
        if is_excluded_bot(name, email, role):
            stats["excluded_bots"] += 1
            return
        if is_agent_record(name, email, role):
            cname = canonical_agent_name(name)
            ckey = cname.lower()
            ent = agents.setdefault(
                ckey,
                {"name": cname, "emails": Counter(), "link": None, "roles": set(), "first_sha": sha},
            )
            if any(c.isupper() for c in cname) and not any(c.isupper() for c in ent["name"]):
                ent["name"] = cname
            m_gh = GH_NOREPLY_RE.match(email)
            if m_gh:
                gh_user = m_gh.group(2)
                norm_em = (
                    f"{m_gh.group(1)}+{gh_user}@users.noreply.github.com"
                    if m_gh.group(1)
                    else f"{gh_user}@users.noreply.github.com"
                )
                ent["emails"][norm_em.lower()] += 1
                ent["emails"][email.lower()] += 0
                if m_gh.group(3) or "-assist" in gh_user.lower():
                    ent["link"] = f"https://github.com/apps/{gh_user}"
            else:
                ent["emails"][email.lower()] += 1
            ent["roles"].add(role)
            return

        el = email.lower()
        nl = name.lower()
        escaped_name_key = escape_md_cell(name).lower()
        escaped_email_key = escape_md_cell(email).lower()
        pair = (nl, el)
        existing_ent = human_by_pair.get(pair)
        if existing_ent is not None:
            existing_ent["roles"].add(role)
            return

        # 仅使用强账户标识进行人类身份关联；绝不以裸显示名跨不同邮箱假合并
        keys = {f"email:{el}", f"email:{escaped_email_key}", f"pair:{nl}|{el}", f"pair:{escaped_name_key}|{escaped_email_key}"}
        ghids: set[str] = set()
        links: set[str] = set()
        m_gh = GH_NOREPLY_RE.match(email)
        if m_gh:
            gh_id, gh_u = m_gh.group(1), m_gh.group(2)
            if gh_id:
                ghids.add(gh_id)
                keys.add(f"ghid:{gh_id}")
            keys.add(f"gh:{gh_u.lower()}")
            links.add(f"https://github.com/{gh_u}")
        cu = extract_mirror_user(email)
        if cu:
            keys.add(f"mirror:{cu.lower()}")
            if platform != "github" and mirror_base:
                links.add(f"{mirror_base}/u/{cu}")
            elif platform == "github" and owner_lower and cu.lower() == owner_lower:
                links.add(f"https://github.com/{repo_owner}")

        human_by_pair[pair] = {
            "names": {name},
            "emails": {email},
            "links": links,
            "roles": {role},
            "keys": keys,
            "ghids": ghids,
            "first_sha": sha,
        }

    for rec in raw.split("\x1e"):
        rec = rec.strip("\r\n")
        if not rec:
            continue
        parts = rec.split("\x00")
        if len(parts) < 7:
            continue
        sha, subject, an, ae, cn, ce, trailers = parts[:7]
        stats["commits"] += 1
        subj = subject.strip()
        if (
            (subj.startswith("chore(authors):") or subj.startswith("chore(licenses):"))
            and is_excluded_bot(an, ae, "Author")
            and is_excluded_bot(cn, ce, "Committer")
        ):
            stats["skipped_bot_commits"] += 1
            continue
        record(sha, cn, ce, "Committer")
        record(sha, an, ae, "Author")
        for t in trailers.split("\x1f"):
            t = t.strip()
            if not t:
                continue
            m = TRAILER_RE.match(t)
            if m:
                record(sha, m.group(1), m.group(2), "Co-authored-by")

    # 倒排索引合并：仅在强账户键有交集且不存在互斥 ghid 时合并
    groups: dict[int, dict] = {}
    key_to_groups: dict[str, set[int]] = {}
    next_gid = 0
    for item in human_by_pair.values():
        candidate_ids: set[int] = set()
        for k in item["keys"]:
            candidate_ids.update(key_to_groups.get(k, ()))
        matched_ids = [
            gid
            for gid in sorted(candidate_ids)
            if gid in groups
            and not (groups[gid]["ghids"] and item["ghids"] and groups[gid]["ghids"].isdisjoint(item["ghids"]))
        ]
        if not matched_ids:
            gid = next_gid
            next_gid += 1
            groups[gid] = item
            for k in item["keys"]:
                key_to_groups.setdefault(k, set()).add(gid)
        else:
            primary_id = matched_ids[0]
            primary = groups[primary_id]
            for other_id in matched_ids[1:]:
                other = groups.get(other_id)
                if not other:
                    continue
                if primary["ghids"] and other["ghids"] and primary["ghids"].isdisjoint(other["ghids"]):
                    continue
                primary["names"] |= other["names"]
                primary["emails"] |= other["emails"]
                primary["links"] |= other["links"]
                primary["roles"] |= other["roles"]
                primary["keys"] |= other["keys"]
                primary["ghids"] |= other["ghids"]
                for k in other["keys"]:
                    s = key_to_groups.get(k)
                    if s:
                        s.discard(other_id)
                        s.add(primary_id)
                del groups[other_id]
            primary["names"] |= item["names"]
            primary["emails"] |= item["emails"]
            primary["links"] |= item["links"]
            primary["roles"] |= item["roles"]
            primary["keys"] |= item["keys"]
            primary["ghids"] |= item["ghids"]
            for k in item["keys"]:
                key_to_groups.setdefault(k, set()).add(primary_id)

    merged = list(groups.values())
    agent_list = []
    for ckey in sorted(agents.keys()):
        ent = agents[ckey]
        nonzero = Counter({k: v for k, v in ent["emails"].items() if v > 0}) or ent["emails"]
        agent_list.append(
            {
                "name": ent["name"],
                "ckey": ckey,
                "cemail": pick_agent_email(ent["name"], nonzero),
                "all_emails": {e.lower() for e in ent["emails"]},
                "link": ent["link"],
                "roles": [r for r in ROLE_ORDER if r in ent["roles"]],
                "first_sha": ent["first_sha"],
            }
        )
    stats["humans_detected"] = len(merged)
    stats["agents_detected"] = len(agent_list)
    return merged, agent_list, stats


def extract_account_keys(text: str, *, include_gh_name_key: bool = False) -> tuple[set[str], set[str]]:
    keys: set[str] = set()
    ghids: set[str] = set()
    candidates = set(EMAIL_FIND_RE.findall(text))
    # 同步解析反引号中的逗号分隔账户项（如非标准 TLD / IP 邮箱）
    for span in re.findall(r"`([^`]+)`", text):
        for part in span.split(","):
            tok = part.strip()
            if "@" in tok and not tok.startswith(("http://", "https://")) and " " not in tok:
                candidates.add(tok)
    for em in candidates:
        el = em.lower()
        keys.add(f"email:{el}")
        m_gh = GH_NOREPLY_RE.match(el)
        if m_gh:
            gh_id, gh_u = m_gh.group(1), m_gh.group(2)
            if gh_id:
                ghids.add(gh_id)
                keys.add(f"ghid:{gh_id}")
            keys.add(f"gh:{gh_u.lower()}")
            if include_gh_name_key:
                keys.add(f"name:{gh_u.lower()}")
        cu = extract_mirror_user(el)
        if cu:
            keys.add(f"mirror:{cu.lower()}")
            if include_gh_name_key:
                keys.add(f"name:{cu.lower()}")
    for gh_u in GH_URL_RE.findall(text):
        gl = gh_u.lower()
        if gl not in {"apps", "topics", "orgs", "features"}:
            keys.add(f"gh:{gl}")
            if include_gh_name_key:
                keys.add(f"name:{gl}")
    for cu in MIRROR_URL_RE.findall(text):
        cl = cu.lower()
        keys.add(f"mirror:{cl}")
        if include_gh_name_key:
            keys.add(f"name:{cl}")
    return keys, ghids


def _strip_role_suffix(cell: str) -> str:
    stripped = ROLE_SUFFIX_RE.sub("", cell.strip()).strip("` ")
    return normalize_space(stripped)


def sync_manifest(
    repo: Path,
    manifest_text: str,
    *,
    platform: str = "github",
    check_only: bool = False,
    dry_run: bool = False,
) -> tuple[str, bool, list[dict], dict[str, int]]:
    """Incrementally append newly discovered human contributors and AI tools into ASSETS_LICENSES.md."""
    humans, agent_list, stats = collect_git_identities(
        repo, platform=platform, check_only=check_only, dry_run=dry_run
    )
    had_trailing_nl = manifest_text.endswith("\n")
    lines = manifest_text.splitlines()

    sec = ""
    t11_last = -1
    t12_last = -1
    t2_last = -1
    t2_placeholder_idx = -1
    max_p = 0
    max_auth = 0
    max_t = 0
    human_rows: list[tuple[set[str], set[str]]] = []
    human_key_index: dict[str, set[int]] = {}
    agent_keys: set[str] = set()
    real_agent_rows = 0
    fence: tuple[str, int] | None = None
    in_fence_line: list[bool] = [False] * len(lines)

    def _add_human_row(row_keys: set[str], row_ghids: set[str]) -> None:
        ridx = len(human_rows)
        human_rows.append((row_keys, row_ghids))
        for k in row_keys:
            human_key_index.setdefault(k, set()).add(ridx)

    for i, raw in enumerate(lines):
        if fence is None:
            m_open = FENCE_OPEN_RE.match(raw)
            if m_open:
                fence_marker = m_open.group(1)
                if not (fence_marker[0] == "`" and "`" in m_open.group(2)):
                    fence = (fence_marker[0], len(fence_marker))
                    in_fence_line[i] = True
                    continue
        else:
            in_fence_line[i] = True
            fchar, flen = fence
            stripped_indent = raw.lstrip(" ")
            if len(raw) - len(stripped_indent) <= 3 and stripped_indent.startswith(fchar * flen):
                rest = stripped_indent.lstrip(fchar)
                if not rest.strip():
                    fence = None
            continue

        # 跳过 CommonMark 4 空格或 Tab 缩进代码块（含 1~3 空格接 Tab）
        if raw.expandtabs(4).startswith("    "):
            in_fence_line[i] = True
            continue

        s = raw.strip()
        if s.startswith("## "):
            if s.startswith("## 一、"):
                sec = "1"
            elif s.startswith("## 二、"):
                sec = "2"
            else:
                sec = "other"
            continue
        if sec.startswith("1") and s.startswith("### "):
            if s.startswith("### 1.1"):
                sec = "1.1"
            elif s.startswith("### 1.2"):
                sec = "1.2"
            elif s.startswith("### 1.3"):
                sec = "1.3"
            else:
                sec = "1.other"
            continue
        if sec == "2" and s.startswith("### "):
            continue
        if sec not in ("1.1", "1.2", "2") or not s.startswith("|"):
            continue
        if re.match(r"^\|[\s:|-]+\|$", s):
            if sec == "1.1":
                t11_last = i
            elif sec == "1.2":
                t12_last = i
            elif sec == "2":
                t2_last = i
            continue

        cols = split_md_row(s)
        c0 = cols[0].strip("` ") if cols else ""
        if sec == "1.1":
            t11_last = i
            if c0 in ("记录编号",) or c0.startswith("["):
                continue
            m_id = re.match(r"^P-(\d+)$", c0)
            if m_id:
                max_p = max(max_p, int(m_id.group(1)))
            row_keys: set[str] = set()
            row_ghids: set[str] = set()
            if len(cols) >= 3:
                disp = _strip_role_suffix(cols[1])
                ekeys, eghids = extract_account_keys(cols[2])
                row_keys |= ekeys
                row_ghids |= eghids
                if disp:
                    dn = disp.lower()
                    for ek in list(ekeys):
                        if ek.startswith("email:"):
                            row_keys.add(f"pair:{dn}|{ek[6:]}")
            _add_human_row(row_keys, row_ghids)
        elif sec == "1.2":
            t12_last = i
            if c0.startswith("授权记录编号") or c0.startswith("["):
                continue
            for aid_num in re.findall(r"\bAUTH-(\d+)\b", cols[0]):
                max_auth = max(max_auth, int(aid_num))
        elif sec == "2":
            t2_last = i
            if c0.startswith("工具记录编号") or c0.startswith("["):
                continue
            tid_part = re.split(r"[；;]", c0, maxsplit=1)[0].strip("` ")
            if tid_part == "T-00":
                t2_placeholder_idx = i
                continue
            real_agent_rows += 1
            m_tid = re.match(r"^T-(\d+)$", tid_part)
            if m_tid:
                max_t = max(max_t, int(m_tid.group(1)))
            raw_aname = re.sub(r"^`?T-\d+`?\s*[；;]\s*", "", cols[0]).strip()
            aname = _strip_role_suffix(raw_aname)
            if aname:
                agent_keys.add(f"name:{aname.lower()}")
                agent_keys.add(f"name:{canonical_agent_name(aname).lower()}")
            if len(cols) >= 2:
                akeys, _ = extract_account_keys(cols[1], include_gh_name_key=True)
                agent_keys.update(akeys)

    stats["existing_humans"] = len(human_rows)
    stats["existing_agents"] = real_agent_rows

    if t11_last < 0 or t12_last < 0 or t2_last < 0:
        raise RuntimeError(
            f"ASSETS_LICENSES.md 缺少必要表格锚点 (t11={t11_last}, t12={t12_last}, t2={t2_last})，拒绝静默跳过"
        )

    new_11: list[str] = []
    new_12: list[str] = []
    added_items: list[dict] = []

    for ent in humans:
        cand_rows: set[int] = set()
        for k in ent["keys"]:
            cand_rows.update(human_key_index.get(k, ()))
        already = any(
            not (human_rows[ridx][1] and ent["ghids"] and human_rows[ridx][1].isdisjoint(ent["ghids"]))
            for ridx in cand_rows
        )
        if already:
            continue
        max_p += 1
        max_auth += 1
        pid = f"P-{max_p:02d}"
        aid = f"AUTH-{max_auth:02d}"
        raw_dname = sorted(ent["names"], key=name_sort_key)[0]
        dname = escape_md_cell(raw_dname)
        emails_str = escape_md_cell(", ".join(sorted(ent["emails"], key=email_sort_key)))
        links = [escape_md_cell(l) for l in sorted(ent["links"])]
        acct = f"`{', '.join(links)}` / `{emails_str}`" if links else f"`{emails_str}`"
        roles = ", ".join(r for r in ROLE_ORDER if r in ent["roles"])
        new_11.append(
            f"| `{pid}` | {dname}（Git 贡献者；Git 角色：{roles}） | {acct} | "
            f"见本仓库 Git 提交历史（待维护者核实具体材料与权属范围） | 本仓库 Git 提交历史（自动检测新增） | `{CONSENT_NO}`（见 `{aid}`） |"
        )
        new_12.append(
            f"| `{aid}`；`{pid}` | {dname}（尚未核实实际声明主体与代表权限） | "
            f"见本仓库 Git 历史中对应提交（待核实） | 未覆盖（尚无可核实明确同意；自动化工作流不代授同意） | "
            f"未覆盖（尚无可核实明确授权；不得由提交记录推定） | 尚无可核实明确意见；依 v1.6.7-r4 第 1.7—1.9 款保留原基础许可边界 |"
        )
        _add_human_row(set(ent["keys"]), set(ent["ghids"]))
        added_items.append({"kind": "human", "id": pid, "name": dname, "roles": roles, "commit": ent["first_sha"][:8]})

    new_2: list[str] = []
    for agent in agent_list:
        hit = f"name:{agent['ckey']}" in agent_keys or any(
            f"email:{em}" in agent_keys for em in agent["all_emails"]
        )
        if hit:
            continue
        max_t += 1
        tid = f"T-{max_t:02d}"
        safe_aname = escape_md_cell(agent["name"])
        safe_email = escape_md_cell(agent["cemail"])
        acct = f"`{safe_email}`" + (f"（{agent['link']}）" if agent["link"] else "")
        roles = ", ".join(agent["roles"])
        new_2.append(
            f"| `{tid}`；{safe_aname}（AI 编程辅助工具） | {acct} | "
            f"在人类维护者指令、审阅与提交操作下参与工程辅助（Git 字段角色：{roles}） | "
            f"见本仓库 Git 提交历史 `Co-authored-by` / 工具记录 | 待关联实际人类主体（工具本身非版权许可授权主体） | "
            f"由工作流自 Git 历史自动登记；工具本身不标注附加条款同意状态，依 v1.6.7-r4 第 1.4、1.8 款处理 |"
        )
        agent_keys.add(f"name:{agent['ckey']}")
        agent_keys.update(f"email:{em}" for em in agent["all_emails"])
        added_items.append({"kind": "agent", "id": tid, "name": safe_aname, "roles": roles, "commit": agent["first_sha"][:8]})

    if not new_11 and not new_2:
        return manifest_text, False, [], stats

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_lines = [
        re.sub(
            r"^(\*\*清单最后更新日期：\*\*\s*)(?:`[^`\n]+`|[^`\n]*?(?=[ \t]*$))([ \t]*)$",
            lambda m: f"{m.group(1)}`{today}`{m.group(2)}" if m.group(0)[len(m.group(1)):].lstrip().startswith("`") else f"{m.group(1)}{today}{m.group(2)}",
            line,
        )
        if (not in_fence_line[idx] and line.startswith("**清单最后更新日期：**"))
        else line
        for idx, line in enumerate(lines)
    ]

    insertions: list[tuple[int, int, list[str]]] = []
    if new_11:
        insertions.append((t11_last + 1, 0, new_11))
    if new_12:
        insertions.append((t12_last + 1, 0, new_12))
    if new_2:
        if t2_placeholder_idx >= 0 and real_agent_rows == 0:
            insertions.append((t2_placeholder_idx, 1, new_2))
        else:
            insertions.append((t2_last + 1, 0, new_2))
    for pos, span, rows in sorted(insertions, key=lambda x: x[0], reverse=True):
        out_lines[pos : pos + span] = rows

    new_text = "\n".join(out_lines) + ("\n" if had_trailing_nl else "")
    return new_text, True, added_items, stats


def write_step_summary(repo_name: str, stats: dict[str, int], added_items: list[dict], new_hash: str, status_text: str) -> None:
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_file:
        return
    safe_repo = escape_md_cell(repo_name)
    rows = [
        f"### `ASSETS_LICENSES.md` 同步核验 · `{safe_repo}`",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 扫描提交数 | {stats.get('commits', 0)} |",
        f"| 识别人类 / AI 工具 | {stats.get('humans_detected', 0)} / {stats.get('agents_detected', 0)} |",
        f"| 既有清单元组 | {stats.get('existing_humans', 0)} / {stats.get('existing_agents', 0)} |",
        f"| 过滤自动化账号次数 | {stats.get('excluded_bots', 0)} |",
        f"| 本次新增记录数 | {len(added_items)} |",
        f"| 结果状态 | {status_text} |",
        f"| 内容 SHA-256 | `{new_hash}` |",
        "",
    ]
    if added_items:
        rows += [
            "| 编号 | 类型 | 名称 | Git 角色 | 首次出现提交 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in added_items:
            rows.append(
                f"| `{item['id']}` | {item['kind']} | {item['name']} | {item['roles']} | `{item['commit']}` |"
            )
        rows.append("")
    with open(summary_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(rows))


def _update_github_hash_var(new_hash: str) -> None:
    if os.environ.get("UPDATE_MANIFEST_VAR") != "true":
        return
    saved_hash = os.environ.get("SAVED_MANIFEST_HASH", "").strip()
    if saved_hash == new_hash:
        return
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    repo_slug = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not (gh_token and repo_slug):
        return
    r1 = subprocess.run(
        ["gh", "variable", "set", "ASSETS_LICENSES_HASH", "-R", repo_slug, "--body", new_hash],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r1.returncode == 0:
        log("已更新 Actions Variable (ASSETS_LICENSES_HASH)。")
    else:
        log(f"警告：更新 Actions Variable 失败（退出码 {r1.returncode}）：{redact_url_userinfo(r1.stderr.strip())}")


def _validate_mirror_endpoint(base: str) -> None:
    parts = urlsplit(base)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise RuntimeError(f"非法的镜像端点 URL：{base}")
    if scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"拒绝通过非加密 HTTP 端点推送镜像凭据：{base}")


def _push_mirror(repo_dir: Path, base: str, slug: str, user: str, tok: str, branch: str) -> None:
    _validate_mirror_endpoint(base)
    auth_b64 = base64.b64encode(f"{user}:{tok}".encode("utf-8")).decode("ascii")
    push_env = dict(os.environ)
    push_env["GIT_TERMINAL_PROMPT"] = "0"
    push_env.pop("GIT_CONFIG_PARAMETERS", None)
    try:
        idx = max(0, int(push_env.get("GIT_CONFIG_COUNT", "0")))
    except ValueError:
        idx = 0
    push_env["GIT_CONFIG_COUNT"] = str(idx + 4)
    push_env[f"GIT_CONFIG_KEY_{idx}"] = f"http.{base}/.extraHeader"
    push_env[f"GIT_CONFIG_VALUE_{idx}"] = ""
    push_env[f"GIT_CONFIG_KEY_{idx + 1}"] = f"http.{base}/.extraHeader"
    push_env[f"GIT_CONFIG_VALUE_{idx + 1}"] = f"AUTHORIZATION: Basic {auth_b64}"
    push_env[f"GIT_CONFIG_KEY_{idx + 2}"] = f"http.{base}/{slug}.extraHeader"
    push_env[f"GIT_CONFIG_VALUE_{idx + 2}"] = ""
    push_env[f"GIT_CONFIG_KEY_{idx + 3}"] = f"http.{base}/{slug}.extraHeader"
    push_env[f"GIT_CONFIG_VALUE_{idx + 3}"] = f"AUTHORIZATION: Basic {auth_b64}"

    push_res = subprocess.run(
        ["git", "-C", str(repo_dir), "push", "--no-verify", f"{base}/{slug}", f"HEAD:refs/heads/{branch}", "-o", "ci.skip"],
        env=push_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if push_res.returncode != 0:
        err_text = "\n".join(p for p in (push_res.stderr, push_res.stdout) if p and p.strip())
        for secret in (tok, quote(tok, safe=""), quote(tok), quote_plus(tok), auth_b64):
            if secret:
                err_text = err_text.replace(secret, "***")
        err_text = redact_url_userinfo(err_text)
        raise RuntimeError(f"镜像推送失败（退出码 {push_res.returncode}）：{err_text.strip()}")


class _UniqueRepoAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, "_repo_seen", False):
            parser.error("不允许多次指定 --repo")
        setattr(namespace, self.dest, values)
        setattr(namespace, "_repo_seen", True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platform", nargs="?", default="github", choices=("github", "mirror"))
    parser.add_argument("--check", action="store_true", help="仅校验是否缺少新增贡献者，发现差异以退出码 1 失败")
    parser.add_argument("--dry-run", action="store_true", help="仅预演统计，不写回文件或提交")
    parser.add_argument("--repo", default=".", action=_UniqueRepoAction, help="目标仓库目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    platform: str = ns.platform
    if not str(ns.repo).strip():
        raise RuntimeError("目标仓库目录 --repo 不能为空。")
    repo_dir = Path(ns.repo).resolve()
    check_only: bool = ns.check
    dry_run: bool = ns.dry_run

    if not repo_dir.is_dir():
        raise RuntimeError(f"目标目录 {repo_dir} 不存在。")
    if not is_git_repo(repo_dir):
        raise RuntimeError(f"目录 {repo_dir} 不是有效的 Git 仓库，无法校验 ASSETS_LICENSES.md。")
    manifest_path = repo_dir / "ASSETS_LICENSES.md"
    if not manifest_path.is_file():
        log("未找到根目录 ASSETS_LICENSES.md，跳过同步。")
        return 0
    if not has_head_commit(repo_dir):
        log("当前仓库尚无 Git 提交（unborn HEAD），跳过同步。")
        return 0

    is_gha = os.environ.get("GITHUB_ACTIONS") == "true"
    if is_gha:
        log("::group::ASSETS_LICENSES.md 贡献历史扫描详情")

    existing = manifest_path.read_text("utf-8")
    new_text, file_changed, added_items, stats = sync_manifest(
        repo_dir,
        existing,
        platform=platform,
        check_only=check_only,
        dry_run=dry_run,
    )
    new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()

    added_desc = ", ".join(f"{x['id']}:{x['name']}@{x['commit']}" for x in added_items) or "无"
    log(
        f"扫描提交 {stats['commits']} 条，识别人类 {stats['humans_detected']} / AI {stats['agents_detected']} "
        f"（既有清单 {stats['existing_humans']} / {stats['existing_agents']}，过滤自动化记录 {stats['excluded_bots']} 次）。"
    )
    log(f"清单 SHA-256: {new_hash} | 待新增({len(added_items)}): {added_desc}")
    if is_gha:
        log("::endgroup::")

    if check_only or dry_run:
        status_text = "发现待登记新增记录（仅检查未写入）" if file_changed else "校验通过（无新增）"
        write_step_summary(repo_dir.name, stats, added_items, new_hash, status_text)
        if check_only and file_changed:
            if is_gha:
                log(f"::error::检测到 {len(added_items)} 位未登记的新增人类/AI 记录，请同步 ASSETS_LICENSES.md：{added_desc}")
            return 1
        return 0

    if platform == "github":
        if not file_changed:
            log("ASSETS_LICENSES.md 为最新，无新增人类贡献者或 AI 工具，跳过提交。")
            write_step_summary(repo_dir.name, stats, added_items, new_hash, "已是最新（跳过）")
            _update_github_hash_var(new_hash)
            return 0

        if os.environ.get("GITHUB_REF_TYPE") == "tag":
            log("当前运行在 Tag 引用上，检测到新增条目但不自动写回分支。")
            write_step_summary(repo_dir.name, stats, added_items, new_hash, "Tag 运行跳过分支提交")
            return 0

        manifest_path.write_text(new_text, encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(repo_dir), "add", "ASSETS_LICENSES.md"], check=True, timeout=30)
        if (
            subprocess.run(
                ["git", "-C", str(repo_dir), "diff", "--cached", "--quiet", "--", "ASSETS_LICENSES.md"],
                timeout=30,
            ).returncode
            != 0
        ):
            msg = (
                "chore(licenses): 自动同步 ASSETS_LICENSES.md 新增贡献记录 [skip ci]\n\n"
                "文档: 依据当前完整 Git 提交历史增量登记新增人类贡献者（默认未发表意见）与 AI 辅助工具至 ASSETS_LICENSES.md。\n\n"
                "[skip-hooks]\n"
                "Generated-by: GitHub Actions\n"
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_dir),
                    "-c",
                    "user.name=github-actions[bot]",
                    "-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--no-verify",
                    "-m",
                    msg,
                ],
                check=True,
                timeout=60,
            )
            branch = (os.environ.get("GITHUB_REF_NAME") or "main").strip() or "main"
            subprocess.run(
                ["git", "-C", str(repo_dir), "push", "--no-verify", "origin", f"HEAD:refs/heads/{branch}"],
                check=True,
                timeout=120,
            )
            log(f"已提交并推送更新后的 ASSETS_LICENSES.md 至分支 {branch}。")
            if is_gha:
                log(f"::notice::已自动登记 {len(added_items)} 条新增记录：{added_desc}")
        _update_github_hash_var(new_hash)
        write_step_summary(repo_dir.name, stats, added_items, new_hash, f"已自动提交 {len(added_items)} 条新增")
        return 0

    # 镜像平台分支（先验证必要环境变量与非 Tag 引用，避免留下脏工作区/未推提交）
    if os.environ.get("MIRROR_REF_TYPE") == "tag" or os.environ.get("GITHUB_REF_TYPE") == "tag":
        log("当前运行在 Tag 引用上，镜像模式跳过自动写回分支。")
        return 0
    if not file_changed:
        log("ASSETS_LICENSES.md 无新增贡献者或 AI 工具记录，跳过提交。")
        return 0

    committer_name = (os.environ.get("MIRROR_COMMITTER_NAME") or "mirror-bot[bot]").strip() or "mirror-bot[bot]"
    committer_email = (os.environ.get("MIRROR_COMMITTER_EMAIL") or "noreply@example.test").strip() or "noreply@example.test"
    base = resolve_mirror_base(repo_dir)
    slug = os.environ.get("MIRROR_REPO_SLUG", "").strip()
    user = (os.environ.get("MIRROR_TOKEN_USER") or committer_name).strip() or committer_name
    tok = os.environ.get("MIRROR_TOKEN", "").strip()
    branch = (os.environ.get("MIRROR_BRANCH") or "main").strip() or "main"
    if not (base and slug and tok):
        raise RuntimeError("缺少镜像推送所需环境变量 (endpoint/slug/token)")
    _validate_mirror_endpoint(base)

    manifest_path.write_text(new_text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(repo_dir), "add", "ASSETS_LICENSES.md"], check=True, timeout=30)
    if (
        subprocess.run(
            ["git", "-C", str(repo_dir), "diff", "--cached", "--quiet", "--", "ASSETS_LICENSES.md"],
            timeout=30,
        ).returncode
        != 0
    ):
        msg = (
            "chore(licenses): 自动同步 ASSETS_LICENSES.md 新增贡献记录 [skip ci]\n\n"
            "文档: 依据当前完整 Git 提交历史增量登记新增人类贡献者（默认未发表意见）与 AI 辅助工具至 ASSETS_LICENSES.md。\n\n"
            "[skip-hooks]\n"
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "-c",
                f"user.name={committer_name}",
                "-c",
                f"user.email={committer_email}",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--no-verify",
                "-m",
                msg,
            ],
            check=True,
            timeout=60,
        )
        _push_mirror(repo_dir, base, slug, user, tok, branch)
        log(f"已提交并推送更新后的 ASSETS_LICENSES.md 至镜像分支 {branch}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
