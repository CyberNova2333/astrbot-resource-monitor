#!/usr/bin/env python3
# build-secure-token.py — 读取用户填好的 token-helper.cpp,把每个 token 用随机会话密钥
# 做 XOR 流式加密,产出「只有密文」的新 cpp 交给交叉 g++ 编译。全程不打印任何 token 值。
# 用法: python3 build-secure-token.py <填好token的cpp> <输出cpp> [--- 其余参数给 C]
import re, os, secrets, sys
# 中文 Windows / GBK 区域设置下 Python 默认按本地编码读写标准流：统一走 UTF-8，
# 否则读到的中文会乱码或抛错（抛错多半落进 fail-open 分支），输出 ✘ 等字符也会崩。
for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

SRC = sys.argv[1]
OUT = sys.argv[2]

raw = open(SRC, "r", encoding="utf-8", errors="replace").read()

# 匹配结构:  {"NAME", "VALUE"},   取 name/value(跳过注释里的 e.g.)
pattern = re.compile(r'\{\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\}\s*,')
pairs = pattern.findall(raw)

# 取所有非空项(含 CNB_TOKEN、GH_TOKEN_* 与 PKG_URL_DEFAULT 这类 CDN URL)
nonempty = [(n, v) for (n, v) in pairs if v]
# 公开产物 URL(非密钥)。构建时从环境变量 GUARD_PKG_URL 注入,**不写死在包里**——
# 写死会把发布地址(含私有仓名)带进随包分发的文件:既破坏「包内不含私有仓名、可放 CDN」的前提,
# 又会触发护栏自身的 R1(提交里含私有仓名 → pre-commit 拦截,等于包无法被提交进任何仓库)。
# 未设置该变量时只是不注入 PKG_URL_DEFAULT(部署侧仍可用 HOOK_PACKAGE_URL 显式指定),不算构建失败。
DEFAULT_PKG_URL = os.environ.get("GUARD_PKG_URL", "").strip()
if DEFAULT_PKG_URL and not any(n == "PKG_URL_DEFAULT" for n, _ in nonempty):
    nonempty.append(("PKG_URL_DEFAULT", DEFAULT_PKG_URL))
elif not DEFAULT_PKG_URL and not any(n == "PKG_URL_DEFAULT" for n, _ in nonempty):
    print("NOTE: 未设置 GUARD_PKG_URL，未注入 PKG_URL_DEFAULT（部署时可用 HOOK_PACKAGE_URL 指定）")
# 至少要有一个平台令牌：CNB_TOKEN(主来源)或 GH_*(可选来源)。只填 CNB_TOKEN 是合法配置。
if not any(n.upper().startswith(("CNB_", "GH_")) for n, _ in nonempty):
    print("NO_TOKENS_EXTRACTED")
    sys.exit(1)

key = secrets.token_bytes(32)

def enc(val: str) -> str:
    b = val.encode("utf-8", "replace")
    return bytes(x ^ key[i % 32] for i, x in enumerate(b)).hex()

items = ",\n  ".join('{"%s", "%s"}' % (n, enc(v)) for (n, v) in nonempty)
items += ",\n  {nullptr, nullptr}"
keyarr = ",".join(str(x) for x in key)

tpl = r'''// token-helper.cpp —— 密钥以 XOR 流式密文形式存在二进制里;运行时在内存解密后注入环境变量。
// 安全: 二进制内不含任何明文连续的 token 字符串;解密仅在内存;无论带不带参数都**绝不打印值**。
// 用法: token-helper <命令> [参数...]   —— 解密所有 key 存入环境变量,再 exec 该命令(值只在该子进程环境里)
//        token-helper                  —— 只解密刻写到当前进程环境并打印固定确认语(不打值)
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>

struct TItem { const char* name; const char* hex; };
// —— build 注入:每项 hex 为密文(与 KEY 做 XOR 流式往返) ——
static const TItem ITEMS[] = {
  __ITEMS__
};
static const unsigned char KEY[32] = { __KEY__ };

static unsigned char* dec(const char* hex){
  int n=(int)(strlen(hex)/2);
  unsigned char* out=(unsigned char*)malloc((size_t)n+1);
  if(!out) return nullptr;
  for(int i=0;i<n;i++){ unsigned v=0; sscanf(hex+2*i,"%2x",&v); out[i]=(unsigned char)(v^KEY[i%32]); }
  out[n]=0;
  return out;
}
int main(int argc,char** argv){
  int m=0;
  for(int i=0; ITEMS[i].name; ++i){
    unsigned char* v=dec(ITEMS[i].hex);
    if(v && v[0]){ setenv(ITEMS[i].name,(const char*)v,1); ++m; }
    free(v);
  }
  if(argc>=2){ execvp(argv[1], &argv[1]); fprintf(stderr,"token-helper: exec %s 失败\n", argv[1]); return 127; }
  printf("环境变量已刻写 %d 项\n", m);
  return 0;
}
'''

tpl = tpl.replace("__ITEMS__", items).replace("__KEY__", keyarr)
os.makedirs(os.path.dirname(os.path.abspath(OUT)) or ".", exist_ok=True)
open(OUT, "w", encoding="utf-8").write(tpl)

print("ENC_OK tokens=%d" % len(nonempty))
print("key_bytes=%d out=%s" % (len(key), OUT))
# 不打印任何值
