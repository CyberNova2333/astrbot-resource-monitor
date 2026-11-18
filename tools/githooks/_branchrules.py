# -*- coding: utf-8 -*-
"""分支名判据。pre-push 钩子与 tools/check-branch-hygiene.py 共用这一份。

判据只有一份，因为两处查的是同一件事、只是时刻不同（推之前 / 体检时）。
各写一遍就会慢慢长歪，而长歪的表现是「体检说行、推的时候被拦」。

## 规则（AGENTS.md §0）

远端只该存在两类 ref：

    main                唯一长期分支，日常改动直接提这里
    <类>/<用途>          例外分支，类只有 hotfix / surgery 两种

**「用途」不是装饰，是这条纪律本身。** 一条叫 `claude/x7f2a` 的分支和没有纪律
是一回事：看名字说不出它在干什么，就没人知道它能不能删、该不该接着用，于是
它永远留在远端。所以判据不只看前缀，还要求 `/` 之后**读得出这条分支在干什么**：

  · 至少两个 kebab 词（`single-thread-reliable`，不是 `fix`）；
  · 纯随机串 / 纯数字 / 纯日期不算用途（`hotfix/a3f9c1` 拦）；
  · 通用词单独用不算用途（`work` `tmp` `wip` `update` `misc` `claude` …）；
  · 允许在用途之后挂日期或短 id 后缀（`surgery/probe-layer-rewrite-20260827`），
    但那是后缀，**不能拿它冒充用途**。

## 宁可漏报也不误报

判据只拦上面这几类**确定**说不出目的的名字。一个会拦下正常分支的检查比没有
检查更糟：被误伤一次的人，下次就会习惯性加 SKIP_BRANCH_HOOK=1。
"""

import re

# 类前缀：只有这两种。没有第三类，也没有「谁开的」这种前缀——
# 分支名要回答的是「在干什么」，不是「谁干的」。
CLASSES = ("hotfix", "surgery")

# 例外分支的寿命上限（小时）。白名单不等于永久居住证。
LIFETIME_HOURS = {"hotfix": 24.0, "surgery": 72.0}

# 名字像 CI 触发器的（AGENTS.md §2：不要用分支触发 CI）
CI_SHAPED = (
    re.compile(r"^ci/"), re.compile(r"^build/"),
    re.compile(r"-driver-"), re.compile(r"-success$"),
    # 分支名里带 run-id 这种长数字。**9 位起**，不是 8 位：日期后缀
    # -YYYYMMDD 正好 8 位，按 8 位会把每一条按规矩起名的分支都误判。
    # GitHub 的 run-id 是 11 位，两者不会撞。
    re.compile(r"\d{9,}"),
)

# 单独出现时说不出目的的词。它们做**限定词**没问题
# （`hotfix/probe-timeout-fix` 合规），只是不能自己撑起一条分支的名字。
FILLER = {
    "work", "works", "tmp", "temp", "wip", "misc", "stuff", "test", "tests",
    "new", "old", "update", "updates", "change", "changes", "patch", "fix",
    "fixes", "dev", "develop", "branch", "session", "task", "job", "run",
    "agent", "bot", "ai", "claude", "codex", "gpt", "kimi", "deepseek",
    "foo", "bar", "baz", "x", "y", "z", "a", "b", "c",
}

DATEISH = re.compile(r"^(?:\d{6,8}|v?\d+(?:\.\d+)*)$")     # 20260827 / 1.2.3
RANDOMISH = re.compile(r"^(?=.*\d)[0-9a-f]{4,}$", re.I)    # f8kli0 / a3f9c1
WORD = re.compile(r"^[a-z0-9][a-z0-9.]*$")


def _meaningful(words):
    """去掉日期/随机串/通用填充词之后，还剩几个能读出意思的词。"""
    keep = []
    for w in words:
        if DATEISH.match(w) or RANDOMISH.match(w) or w in FILLER:
            continue
        keep.append(w)
    return keep


def problems(name):
    """返回这条分支名不合规之处的列表（每项是一段给人看的说明）。

    合规（`main` 或 `<类>/<读得出用途>`）则返回空列表。
    """
    if name == "main":
        return []

    for p in CI_SHAPED:
        if p.search(name):
            return ["`%s` 的名字像 CI 触发器。\n"
                    "      AGENTS.md §2：**永远不要用分支触发 CI**——检查类 workflow\n"
                    "      跟着 push 自己会跑，一次性触发器不要留在远端。" % name]

    if "/" not in name:
        return ["`%s` 没有类前缀。远端只允许 main 和 <类>/<用途>，\n"
                "      类只有：%s（AGENTS.md §0）。"
                % (name, " / ".join(CLASSES))]

    cls, _, purpose = name.partition("/")
    out = []
    if cls not in CLASSES:
        out.append("`%s` 的类前缀 `%s` 不在白名单内。只有 %s 两类。\n"
                   "      前缀要回答「这条分支在干什么」，不是「谁开的」——\n"
                   "      `claude/…` `codex/…` 这种一律不算（AGENTS.md §0 规则一）。"
                   % (name, cls, " / ".join(CLASSES)))

    words = [w for w in purpose.split("-") if w]
    if not words or not all(WORD.match(w) for w in words):
        out.append("`%s` 的用途段必须是小写 kebab（`probe-layer-rewrite`）。" % name)
        return out

    keep = _meaningful(words)
    if len(keep) < 2:
        out.append("`%s` 的用途段说不出这条分支在干什么。\n"
                   "      要求：至少两个能读出意思的 kebab 词；随机串、纯日期、\n"
                   "      `%s` 这类通用词不算用途（可以做后缀或限定词）。\n"
                   "      正例：hotfix/config-fetch-timeout、"
                   "surgery/probe-layer-rewrite-20260827"
                   % (name, " ".join(sorted(FILLER & set(words))) or "work/tmp/fix"))
    return out


def allowed(name):
    return not problems(name)


def lifetime_hours(name):
    """这条分支的寿命上限（小时）；main 或未知类返回 None。"""
    cls = name.partition("/")[0]
    return LIFETIME_HOURS.get(cls)
