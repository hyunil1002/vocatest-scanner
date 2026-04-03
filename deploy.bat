@echo off
set GIT_PATH="C:\Program Files\Git\bin\git.exe"
echo.
echo [VocaTest AI Scanner] 서버(GitHub) 업데이트를 시작합니다...
echo ──────────────────────────────────────────────────
echo.

%GIT_PATH% add .
%GIT_PATH% commit -m "Update from Local Dashboard"
%GIT_PATH% push origin master

echo.
echo ──────────────────────────────────────────────────
echo [VocaTest AI Scanner] 전송이 완료되었습니다!
echo 1~2분 뒤에 실시간 웹 주소(Streamlit Cloud)에 반영됩니다.
echo.
pause
