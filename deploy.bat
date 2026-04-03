@echo off
set "GIT_EXE=C:\Program Files\Git\bin\git.exe"
echo [VocaTest Scanner] Deploying updates to GitHub...
echo.

"%GIT_EXE%" add .
"%GIT_EXE%" commit -m "Update from Dashboard"
"%GIT_EXE%" push origin main

echo.
echo [VocaTest Scanner] Done! Wait 1-2 mins for site update.
pause
