@echo off
chcp 65001 >nul
title Serein - switch updates to the fork
setlocal
set HOST=154.21.200.74
set HERE=%~dp0
set SSHOPT=-o StrictHostKeyChecking=accept-new

echo.
echo  ================================================================
echo    Serein  把更新来源切换到自建 fork
echo  ================================================================
echo    第 1 步  上传两个文件到 VPS（会问两次 VPS 登录密码）
echo    第 2 步  选择只体检，还是直接执行
echo.
echo    执行会停服并重建两个镜像，耗时和首次构建同量级。
echo    中途掉线不会坏数据，但服务可能停在停止状态，重跑一次即可。
echo  ================================================================
echo.
pause

echo.
echo  ---- 1/2 上传到 VPS ----
scp %SSHOPT% "%HERE%cutover-to-fork.sh" root@%HOST%:/tmp/serein-cutover.sh
if errorlevel 1 scp -O %SSHOPT% "%HERE%cutover-to-fork.sh" root@%HOST%:/tmp/serein-cutover.sh
if errorlevel 1 goto fail
scp %SSHOPT% "%HERE%..\scripts\upstream_update.py" root@%HOST%:/tmp/serein-updater.py
if errorlevel 1 scp -O %SSHOPT% "%HERE%..\scripts\upstream_update.py" root@%HOST%:/tmp/serein-updater.py
if errorlevel 1 goto fail

echo.
echo  ---- 2/2 选择动作 ----
echo    1 = 只体检（只读，安全，先跑这个）
echo    2 = 执行切换（直接跑，别关窗口、别断网）
echo    3 = 执行切换（放进 screen，掉线也不断；机器没装 screen 就选 2）
echo    0 = 退出
set "CHOICE="
set /p CHOICE=Choose 1/2/3/0: 
if not defined CHOICE exit /b 0
if "%CHOICE%"=="1" goto check
if "%CHOICE%"=="2" goto apply
if "%CHOICE%"=="3" goto applyscreen
if "%CHOICE%"=="0" exit /b 0
echo.
echo  No such option.
pause
exit /b 2

:check
ssh -t %SSHOPT% root@%HOST% "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py"
goto done

:apply
echo.
echo  执行中，请不要关闭这个窗口，也不要断网。
ssh -t %SSHOPT% root@%HOST% "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py --apply"
goto done

:applyscreen
ssh -t %SSHOPT% root@%HOST% "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py --apply --screen"
goto done

:done
echo.
echo  ---- 会话结束 ----
pause
exit /b 0

:fail
echo.
echo  上传失败：检查网络、IP 和密码，然后重跑这个脚本。
pause
exit /b 1
