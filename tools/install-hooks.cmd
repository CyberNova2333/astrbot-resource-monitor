@echo off
REM ── Windows 上装本仓库的 git 钩子 ────────────────────────────────────
REM
REM 与 tools\install-hooks.sh 等价，只是不用先开 Git Bash。做的事就一件：
REM 把 core.hooksPath 指到受版本控制的 tools/githooks/。
REM
REM 注意：钩子**本身**不是 .bat 也不可能是——git 找的是名为 commit-msg /
REM pre-push（无扩展名）的文件，并且在 Windows 上同样用自带的 sh 执行它们。
REM 所以那两个是 POSIX sh 脚本，由它们再去找 python3 / python / py -3。
REM 能配 .cmd 的只有「给人手动跑一次」的安装动作，也就是本文件。
REM
REM 多数情况根本用不到：Claude 或 Codex 在这个仓库里跑过任意一条命令，
REM tools/agent-guard.py 就已经把这件事做完了。
REM
REM 卸载： git config --unset core.hooksPath

setlocal
cd /d "%~dp0.."

git config core.hooksPath tools/githooks
if errorlevel 1 (
  echo.
  echo X 设置失败。请确认当前目录是本仓库的克隆，且 git 在 PATH 里。
  exit /b 1
)

echo.
echo 已把 core.hooksPath 指向 tools/githooks
echo.
echo   生效的钩子:
echo     commit-msg   提交信息规范^(中文 / Co-authored-by / 文档:^)
echo     pre-push     推送时复查提交信息 + 分支纪律
echo.
echo   自检: git config --get core.hooksPath
endlocal
