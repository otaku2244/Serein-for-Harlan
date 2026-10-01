@echo off
chcp 65001 >nul
title Serein for Harlan - push to GitHub
cd /d "%~dp0.."

type "%~dp0push-to-fork.txt"
echo.
echo ---- self check ----
where git
git --version
echo.
echo ---- remotes ----
git remote -v
echo.
echo ---- latest local commits ----
git log --oneline -5
echo.
pause

echo.
echo ---- pushing ----
git push -u origin main
echo.
echo ---- verifying ----
echo   The two 40-character ids below must be identical:
git ls-remote origin refs/heads/main
git rev-parse main
echo.
pause
