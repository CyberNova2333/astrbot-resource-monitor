// token-helper.cpp —— 护栏运行时凭据数据源(模板)。
//
// 用法:
//   把各 GH_TOKEN_n(只读细粒度)的真值填进下方 TOKENS 的 value 字段;
//   PKG_URL_DEFAULT 为公开护栏产物 URL,通常无需改动。
//   填好后用同级 build-secure-token.py 生成「密文化」最终源码,再交叉编成 x86-64 ELF:
//     python3 build-secure-token.py token-helper.cpp secure-token-helper.cpp
//     x86_64-linux-gnu-g++ -O2 -o token-helper.x64 secure-token-helper.cpp && chmod 700 token-helper.x64
//
// 产出的 ELF 安全属性:
//   - 值以 XOR 流式密文存二进制,运行时仅在内存解密后调用 setenv;
//   - 无论带不带参数都【绝不打印值】:带参数 → 刻写环境变量后 exec 该命令(值只在子进程环境);
//     不带参数 → 只输出固定确认语;
//   - 目的:防止 Claude Code 云对上传文件的自动读取把可用值拉进训练数据(密文非明文即挡),
//     属混淆级,非抗定向逆向;若需真正抗逆向,应改为机器侧注入、代码只读环境变量名。
//
// 说明:本文件为【数据源模板】,不含 main()/打印逻辑;运行时 main 由 build-secure-token.py 生成。
struct Token { const char* name; const char* value; };
static const Token TOKENS[] = {
  {"GH_TOKEN_1", ""},   // 所有者1
  {"GH_TOKEN_2", ""},   // 所有者2
  {"GH_TOKEN_3", ""},   // 所有者3
  {"GH_TOKEN",   ""},   // 兜底(可选)
  {"PKG_URL_DEFAULT", ""},   // 公开产物 URL；构建时由 build-secure-token.py 从 $GUARD_PKG_URL 注入，不在此写死
  {nullptr, nullptr}
};
