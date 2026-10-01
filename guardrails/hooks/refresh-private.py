#!/usr/bin/env python3
# refresh-private.py — 重建 private-repos.json：对**所有所有者**做一次私有仓并集。
#
# 来源(并集):
#   1) 私有种子 policy.private_seed (默认 /root/.claude/private-seed.json)。**只放本机，不随包分发**。
#      云端没有这个文件时，可从环境变量 GUARD_SEED_B64(种子 JSON 的 base64) 或 GUARD_SEED_JSON 读取——
#      与 GH_TOKEN_n 同一暴露面(环境使用者/Agent 可读)，比 PAT 本身更不敏感。
#      格式: {"owners": ["Org1", ...], "private": ["Org1/repo", "repo", ...], "patterns": ["业务域名/标识 正则", ...]}
#      patterns = R4 业务标识(域名/内部流水线名)正则，原样进缓存，由 check.py/scan-repo 应用。
#   2) gh CLI(best-effort，失败不 fail-all)
#   3) 环境变量 GH_TOKEN_1..N(各 Owner 的 Metadata:Read PAT；token-helper ELF 的唯一职责就是把它们写进环境)，
#      以及 GH_TOKEN(云端占位符 'proxy-injected' 忽略)。每次调用失败重试≤3；任一把重试后仍失败 => 整体失败(不回写，退出 1)。
#      403/404 = 该 token 看不到 => 正常跳过；403 且是 rate limit => 算失败(否则会静默漏掉整个 owner)。
#
# 完整性:
#   * 至少一个来源成功(种子/gh 取到数据/任一 token 成功)，否则不回写、退出 1 => 缓存保持缺失/陈旧 => check.py ERROR。
#   * policy.expected_owners 里的每个 owner 必须被"种子覆盖"或"gh/token 看到了它至少 1 个私有仓"，否则视为不完整、
#     不回写。(HTTP 200 不算覆盖: 无权限时 orgs/{o}/repos 返回 200+仅公开仓；云环境 GitHub 代理也只放挂载仓。)
#     某 owner 确实 0 个私有仓 => 把它写进种子的 owners 即可。
#   * expected_owners 为空时上面那条恒真，所以额外要求: 空 expected_owners + 一个私有仓都没看到 => 判定为来源不可信，
#     同样不回写。否则会写出空名单并报成功，R1 静默放行一切(fail open)。
#
#   4) CNB(云原生构建)平台: policy.cnb_token_file 指向的令牌文件(格式见交接说明: `Token: <值>` 一行)，
#      或环境变量 CNB_TOKEN。枚举当前账号可见的全部组织(含子组织)下的非公开仓。
#      语义与 GH_TOKEN_n 相同: 令牌**配置了**就必须成功，任一调用重试后仍失败 => 整体失败(不回写)；
#      没配置(文件不存在且无环境变量) => 跳过。名单形态: `组织路径/仓名`、`子组织/仓名` 与裸名三种。
#      为什么要有它: 托管平台不止 GitHub。一旦 GitHub 侧登录态失效(账号被停用即是实例)，gh 与 GH_TOKEN_n
#      同时哑火，名单退化成只有种子 => private 为空 => 守卫 fail-closed 拦下一切推送。名单来源必须跟着仓库
#      实际所在的平台走，而不是绑死在一家。
#
# 注意 patterns(R4 业务标识正则)只能来自私有种子: gh / GH_TOKEN_n / CNB 都提供不了这类信息。
# 没有种子时 patterns 为空 => R4 整条规则不生效，仅靠 R1 挡私有仓名。
#
# rev4 修复: 去掉写死的私有仓名种子; gh --jq 输出裸字符串(非 JSON)导致 me 永远取不到; user/repos 只翻第 1 页;
#            user/repos 返回的组织仓被错记到 username 下; 路径全部来自 policy.json(bootstrap 只需改写 policy.json)。
import json, subprocess, os, sys, re, urllib.request, urllib.error, time
# 中文 Windows / GBK 区域设置下 Python 默认按本地编码读写标准流：统一走 UTF-8，
# 否则读到的中文会乱码或抛错（抛错多半落进 fail-open 分支），输出 ✘ 等字符也会崩。
for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

# GUARD_POLICY 只为沙盒测试而设: 指向一份临时 policy(临时缓存路径/临时种子)，就能在不碰安装目录的前提下
# 验证来源枚举与解析逻辑。生产路径不设它，永远读安装目录里那份。
POLICY = json.load(open(os.environ.get('GUARD_POLICY') or '/root/.claude/policy/policy.json', encoding='utf-8'))
CACHE = POLICY['private_cache']
SEED = POLICY.get('private_seed', '/root/.claude/private-seed.json')
EXPECTED = set(POLICY.get('expected_owners', []))
TTL = int(POLICY.get('private_cache_ttl', 300))


def fail(msg):
    print('FAIL: ' + msg, file=sys.stderr); print('FAIL'); sys.exit(1)


# ---------- tokens (环境变量) ----------
def all_tokens():
    """返回 [(环境变量名, token)]。"""
    toks = []
    for k in sorted((k for k in os.environ if re.fullmatch(r'GH_TOKEN_\d+', k)), key=lambda k: int(k.split('_')[-1])):
        v = os.environ.get(k, '').strip()
        if v and v not in [t for _, t in toks]:
            toks.append((k, v))
    t = os.environ.get('GH_TOKEN', '').strip()
    if t and t != 'proxy-injected' and t not in [x for _, x in toks]:   # Anthropic 云端 云环境的占位符不是可用 token
        toks.append(('GH_TOKEN', t))
    return toks


# ---------- GitHub REST via token ----------
def api_once(url, tok):
    try:
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok,
                                                   'Accept': 'application/vnd.github+json',
                                                   'User-Agent': 'refresh-private'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return 'resolved', json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            try:
                body = e.read().decode('utf-8', 'replace').lower()
            except Exception:
                body = ''
            if e.code == 403 and ('rate limit' in body or e.headers.get('X-RateLimit-Remaining') == '0'):
                return 'error', None                   # 限流不是"看不到"，是失败
            return 'skipped', None
        return 'error', None
    except Exception:
        return 'error', None


def api_retry(url, tok):
    for _ in range(3):
        kind, val = api_once(url, tok)
        if kind != 'error':
            return kind, val
        time.sleep(1)
    return 'error', None


def api_pages(path, tok):
    """翻页拉全部；返回 (kind, list)。任一页 error => error。"""
    out = []
    for page in range(1, 11):                          # ≤1000 仓/owner
        kind, r = api_retry('https://api.github.com/%s%sper_page=100&page=%d' % (path, '&' if '?' in path else '?', page), tok)
        if kind != 'resolved':
            return kind, out
        if not isinstance(r, list):
            return 'error', out
        out.extend(r)
        if len(r) < 100:
            break
    return 'resolved', out


# ---------- gh CLI (best-effort) ----------
def gh_raw(args, timeout=40):
    try:
        r = subprocess.run(['gh', 'api', *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def gh_json(args):
    out = gh_raw(args)
    if out is None:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def gh_list(path):
    out = []
    for page in range(1, 11):
        r = gh_json(['%s%sper_page=100&page=%d' % (path, '&' if '?' in path else '?', page),
                     '--jq', '[.[]|{name,full_name,private,fork}]'])
        if not isinstance(r, list):
            return None if page == 1 else out
        out.extend(r)
        if len(r) < 100:
            break
    return out


# ---------- collect ----------
priv, owners, covered, sources, patterns, token_owners = set(), set(), set(), [], [], {}


def collect(items):
    """按 full_name 归属 owner(user/repos 会混着返回组织仓)。私有 fork 与上游同名，跳过以免误伤公开上游。
    返回本批看到私有仓的 owner 集合(用于记录 token -> owners，供 resolve-private 优先选 token)。
    只有"看到了该 owner 至少 1 个私有仓"才算覆盖了这个 owner: GitHub 对无权限的 orgs/{o}/repos 返回 200+仅公开仓，
    对被代理过滤的请求也可能返回 200+部分仓，200 本身不代表拿全了。"""
    seen = set()
    for it in items or []:
        if not isinstance(it, dict) or not it.get('private') or it.get('fork'):
            continue
        full = it.get('full_name') or ''
        if '/' not in full:
            continue
        o, nm = full.split('/', 1)
        priv.add(full); priv.add(nm); owners.add(o); covered.add(o); seen.add(o)
    return seen


# 1) 私有种子(本机文件；没有文件则看环境变量)
seed_text = None
if os.path.isfile(SEED):
    seed_text = open(SEED, encoding='utf-8').read()
elif os.environ.get('GUARD_SEED_B64', '').strip():
    import base64
    try:
        seed_text = base64.b64decode(os.environ['GUARD_SEED_B64'].strip()).decode('utf-8')
    except Exception as e:
        fail('GUARD_SEED_B64 解码失败: %s' % type(e).__name__)
elif os.environ.get('GUARD_SEED_JSON', '').strip():
    seed_text = os.environ['GUARD_SEED_JSON']
if seed_text is not None:
    try:
        s = json.loads(seed_text)
        so = set(map(str, s.get('owners', []))); sp = set(map(str, s.get('private', [])))
        owners |= so; covered |= so; priv |= sp
        patterns = [str(x) for x in s.get('patterns', [])]
        for x in patterns:
            re.compile(x)                                # 坏正则在这里就炸，不进缓存
        for p in sp:
            if '/' in p:
                o, nm = p.split('/', 1); owners.add(o); covered.add(o); priv.add(nm)
        sources.append('seed' if os.path.isfile(SEED) else 'seed-env')
    except Exception as e:
        fail('私有种子解析失败: %s' % type(e).__name__)

# 2) gh CLI
me = (gh_raw(['user', '--jq', '.login']) or '').strip() or None     # --jq 输出裸字符串，不是 JSON
if me:
    owners.add(me)
    orgs = gh_json(['user/memberships/orgs', '--jq', '[.[]|.organization.login]'])
    if isinstance(orgs, list):
        owners.update(o for o in orgs if isinstance(o, str))
    mine = gh_list('user/repos?affiliation=owner')
    if mine is not None:
        collect(mine); sources.append('gh')
for o in sorted(owners):
    if o == me:
        continue
    r = gh_list('orgs/%s/repos?type=all' % o)
    if r is not None:
        collect(r)
        if 'gh' not in sources:
            sources.append('gh')

# 3) tokens(每把都必须成功，任一失败 => 整体失败)
for idx, (envname, tok) in enumerate(all_tokens(), 1):
    seen_here = set()
    kind, u = api_retry('https://api.github.com/user', tok)
    if kind == 'error':
        fail('token #%d 调用 /user 失败(网络/限流/无效)' % idx)
    login = u.get('login') if kind == 'resolved' and isinstance(u, dict) else None
    if login:
        owners.add(login)
    kind, mine = api_pages('user/repos?affiliation=owner', tok)
    if kind == 'error':
        fail('token #%d 枚举 user/repos 失败' % idx)
    if kind == 'resolved':
        seen_here |= collect(mine)
    for o in sorted(owners):
        if o == login:
            continue
        kind, r = api_pages('orgs/%s/repos?type=all' % o, tok)
        if kind == 'error':
            fail('token #%d 枚举 orgs/%s/repos 失败' % (idx, o))
        if kind == 'resolved':
            seen_here |= collect(r)
    token_owners[envname] = sorted(seen_here)
    sources.append('token%d' % idx)

# 4) CNB 平台(令牌配置了就必须成功；没配置就跳过)
CNB_API = POLICY.get('cnb_api', 'https://api.cnb.cool').rstrip('/')
CNB_TOKEN_FILE = POLICY.get('cnb_token_file', '/root/.cnb-auth-token')
cnb_groups = []


def cnb_token():
    t = os.environ.get('CNB_TOKEN', '').strip()
    if t:
        return t
    if os.path.isfile(CNB_TOKEN_FILE):
        m = re.search(r'(?m)^Token:[ \t]*(\S+)', open(CNB_TOKEN_FILE, encoding='utf-8').read())
        if m:
            return m.group(1)
    return None


def cnb_api_once(path, tok):
    """CNB OpenAPI: Bearer + 必须带 accept: application/json(否则 406)。语义同 api_once。"""
    try:
        req = urllib.request.Request(CNB_API + path, headers={'Authorization': 'Bearer ' + tok,
                                                              'accept': 'application/json',
                                                              'User-Agent': 'refresh-private'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 'resolved', json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return 'skipped', None
        return 'error', None
    except Exception:
        return 'error', None


def cnb_api_retry(path, tok):
    for _ in range(3):
        kind, val = cnb_api_once(path, tok)
        if kind != 'error':
            return kind, val
        time.sleep(1)
    return 'error', None


def cnb_pages(path, tok):
    """翻页拉全部；列表接口可能直接返回数组，也可能包在 list/items 里。"""
    out = []
    for page in range(1, 11):
        kind, r = cnb_api_retry('%s%spage=%d&page_size=100' % (path, '&' if '?' in path else '?', page), tok)
        if kind != 'resolved':
            return kind, out
        items = r if isinstance(r, list) else (r.get('list') or r.get('items') or []) if isinstance(r, dict) else None
        if items is None:
            return 'error', out
        out.extend(items)
        if len(items) < 100:
            break
    return 'resolved', out


def cnb_collect(group_path, items):
    """CNB 仓库对象用 visibility_level 标可见性(Public/Private/Secret…)；非 Public 一律当私有。
    名单写三种形态: 完整路径、末段子组织/仓名、裸名——检查器按子串匹配，裸名才是主要判据。
    组织路径的每一段都当作 owner 记录: R1 不关心平台，只关心"这个词是不是某个私有仓的名字/归属"。"""
    seen = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        vis = str(it.get('visibility_level') or it.get('visibility') or '')
        if vis.lower() == 'public':
            continue
        nm = it.get('name') or ''
        full = it.get('path') or ('%s/%s' % (group_path, nm) if nm else '')
        if not nm or not full:
            continue
        priv.add(full); priv.add(nm)
        segs = full.split('/')
        if len(segs) >= 2:
            priv.add('/'.join(segs[-2:]))
        for o in segs[:-1]:
            owners.add(o); covered.add(o); seen.add(o)
    return seen


_cnb_tok = cnb_token()
if _cnb_tok:
    kind, groups = cnb_pages('/user/groups', _cnb_tok)
    if kind == 'error':
        fail('CNB 令牌已配置，但枚举 /user/groups 失败(网络/令牌无效)')
    # 组织可能有子组织；逐层展开。对象里带 path(完整路径)。
    queue = [g.get('path') for g in (groups or []) if isinstance(g, dict) and g.get('path')]
    seen_paths = set()
    while queue:
        gp = queue.pop(0)
        if gp in seen_paths:
            continue
        seen_paths.add(gp)
        kind, subs = cnb_pages('/user/groups/%s' % gp, _cnb_tok)
        if kind == 'error':
            fail('CNB 枚举子组织 %s 失败' % gp)
        for s in subs or []:
            if isinstance(s, dict) and s.get('path'):
                queue.append(s['path'])
        kind, repos = cnb_pages('/%s/-/repos' % gp, _cnb_tok)
        if kind == 'error':
            fail('CNB 枚举 %s 下的仓库失败' % gp)
        if kind == 'resolved':
            cnb_collect(gp, repos)
    cnb_groups = sorted(seen_paths)
    sources.append('cnb')

# ---------- 完整性 ----------
if not sources:
    fail('没有任何可用来源(无私有种子、gh 不可用、环境里没有 GH_TOKEN_n)。不回写，缓存保持缺失/陈旧 => 守卫按 ERROR 拦截')
missing = sorted(EXPECTED - covered)
if missing:
    fail('以下 owner 未被任何来源覆盖(种子未列出, gh/token 也没看到它的任何私有仓): %s => 名单不完整，不回写' % ', '.join(missing))
# expected_owners 没配时上面那道校验恒真(空集合减任何东西都是空)，于是"一个私有仓都没看到"会被当成成功，
# 写出 private:[] 的缓存 => R1 静默放行一切。这与本包"守卫自身判断失败 = fail closed"的原则相反，
# 而"确实没有私有仓"和"scope 不足 / 被代理过滤 / 登录态失效"从结果上无法区分，只能保守当作后者。
# 确实一个私有仓都没有的部署：把 owner 写进私有种子的 owners(或 policy.expected_owners)即可通过。
if not EXPECTED and not priv:
    fail('policy.expected_owners 未配置，且没有从任何来源看到私有仓 —— 无法区分"确实没有"与"权限不足/被过滤"。'
         '不回写(否则会写出空名单，R1 会静默放行一切)。请配置 expected_owners，或在私有种子里列出 owners/private')

now = time.time()
os.makedirs(os.path.dirname(CACHE), exist_ok=True)
tmp = CACHE + '.tmp'
json.dump({'generated_at': now, 'expires_at': now + TTL, 'status': 'fresh',
           'sources': sources, 'covered_owners': sorted(covered),
           'private': sorted(priv), 'owners': sorted(owners), 'patterns': patterns, 'token_owners': token_owners,
           'cnb_groups': cnb_groups},
          open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
os.replace(tmp, CACHE)                                   # 原子替换，check.py 不会读到半截文件
print('private=%d owners=%d patterns=%d sources=%s ttl=%ds' % (len(priv), len(owners), len(patterns), '+'.join(sources), TTL))
