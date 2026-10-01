@echo off
chcp 65001 >nul
title Serein for Harlan - push to GitHub
cd /d "%~dp0.."

echo.
echo  ================================================================
echo    把本地的 Serein-for-Harlan 推到 GitHub
echo  ================================================================
echo    推送时会要求登录 GitHub（会弹浏览器授权）。
echo    凭据由系统保管，不会写进这个脚本，也不会留在项目里。
echo  ================================================================
echo.
echo  ---- 环境自检 ----
where git
git --version
echo.
echo  ---- 远端地址 ----
git remote -v
echo.
echo  ---- 本地最近的提交 ----
git log --oneline -5
echo.
pause

echo.
echo  ---- 开始推送 ----
git push -u origin main
echo.
echo  ---- 校验 ----
echo   下面两行 40 位编号应当完全一致：
git ls-remote origin refs/heads/main
git rev-parse main
echo.
pause
