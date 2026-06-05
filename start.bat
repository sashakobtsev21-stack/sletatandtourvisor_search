@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tour Search
set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%"
echo ============================================
echo    Tour Search - запуск сайта
echo ============================================
echo.
rem --- проверка окружения ---
if exist ".venv\Scripts\toursearch.exe" goto :envok
echo [!] Не найдено окружение .venv\Scripts\toursearch.exe
echo     Проект ещё не установлен (см. инструкцию по первому запуску).
echo.
pause
exit /b 1
:envok
echo.
rem --- обновление интерфейса до актуальной версии (если установлен Node) ---
where npm >nul 2>&1 || goto :skipbuild
if not exist "frontend\package.json" goto :skipbuild
echo Обновляю интерфейс, это пара секунд...
pushd frontend
call npm run build
set "BUILD_RC=%errorlevel%"
popd
if "%BUILD_RC%"=="0" (
  echo Интерфейс обновлён.
) else (
  echo [!] Сборка интерфейса упала ^(код %BUILD_RC%^) — запускаю с ПРЕДЫДУЩЕЙ версией интерфейса.
)
:skipbuild
echo.
echo Запускаю сервер в отдельном окне...
start "Tour Search (СЕРВЕР - не закрывать)" ".venv\Scripts\toursearch.exe" web --port %PORT%
echo Жду, пока сервер поднимется...
set /a tries=0
:waitloop
set /a tries+=1
powershell -NoProfile -Command "try { Invoke-WebRequest '%URL%/' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto :serverup
if %tries% geq 20 goto :servertimeout
timeout /t 1 /nobreak >nul
goto :waitloop
:servertimeout
echo [!] Сервер не ответил вовремя. Открываю браузер всё равно —
echo     если сайт не открылся, проверьте чёрное окно сервера на ошибки.
goto :openbrowser
:serverup
echo Сервер готов.
:openbrowser
echo Открываю сайт в браузере: %URL%
start "" "%URL%"
echo.
echo ---------------------------------------------------------
echo  Сайт открыт: %URL%
echo  Открылось отдельное чёрное окно сервера.
echo  ПОКА оно открыто - сайт работает.
echo  Чтобы ОСТАНОВИТЬ сайт - закройте то окно.
echo ---------------------------------------------------------
echo.
echo Это окно можно закрыть.
pause
