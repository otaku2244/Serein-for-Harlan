@echo off
chcp 65001 >nul
title Serein - switch updates to the fork
setlocal
set HOST=154.21.200.74
set HERE=%~dp0
set SSHOPT=-o StrictHostKeyChecking=accept-new

type "%HERE%serein-cutover.txt"
echo.
pause

echo.
echo ---- 1/2  upload to the VPS ----
scp %SSHOPT% "%HERE%cutover-to-fork.sh" root@%HOST%:/tmp/serein-cutover.sh
if errorlevel 1 scp -O %SSHOPT% "%HERE%cutover-to-fork.sh" root@%HOST%:/tmp/serein-cutover.sh
if errorlevel 1 goto fail
scp %SSHOPT% "%HERE%..\scripts\upstream_update.py" root@%HOST%:/tmp/serein-updater.py
if errorlevel 1 scp -O %SSHOPT% "%HERE%..\scripts\upstream_update.py" root@%HOST%:/tmp/serein-updater.py
if errorlevel 1 goto fail

echo.
echo ---- 2/2  choose an action ----
echo    1 = check only      (read only, safe, do this first)
echo    2 = apply           (do not close this window, do not drop the network)
echo    3 = apply in screen (survives a dropped connection)
echo    0 = quit
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
echo  Running. Do not close this window, do not drop the network.
ssh -t %SSHOPT% root@%HOST% "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py --apply"
goto done

:applyscreen
ssh -t %SSHOPT% root@%HOST% "bash /tmp/serein-cutover.sh --updater-file /tmp/serein-updater.py --apply --screen"
goto done

:done
echo.
echo ---- session finished ----
pause
exit /b 0

:fail
echo.
echo  Upload failed. Check the network, the IP and the password, then rerun.
pause
exit /b 1
