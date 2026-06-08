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

rem ============================================================
rem  ПЕРВЫЙ ЗАПУСК: если проект ещё не установлен - ставим сами.
rem  Нужно один раз и занимает несколько минут (скачивание
rem  зависимостей Python и браузера для поиска).
rem ============================================================
if exist ".venv\Scripts\toursearch.exe" goto :envok

echo [Первый запуск] Проект ещё не установлен - устанавливаю.
echo Это нужно сделать ОДИН раз, займёт несколько минут.
echo НЕ закрывайте это окно до конца установки.
echo.

rem --- ищем Python (сначала лаунчер py, потом python) ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo [!] Python не найден на компьютере.
  echo     Установите Python 3.12 или новее: https://www.python.org/downloads/
  echo     При установке ОБЯЗАТЕЛЬНО отметьте галочку "Add python.exe to PATH",
  echo     затем запустите start.bat снова.
  echo.
  pause
  exit /b 1
)

echo [1/4] Создаю виртуальное окружение .venv ...
%PYEXE% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [!] Не удалось создать окружение .venv. Проверьте установку Python.
  echo.
  pause
  exit /b 1
)

echo [2/4] Устанавливаю зависимости Python (несколько минут) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[web,browser]"
if errorlevel 1 (
  echo [!] Установка зависимостей не удалась - смотрите ошибки выше.
  echo.
  pause
  exit /b 1
)

echo [3/4] Скачиваю браузер для поиска (Playwright Chromium) ...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo [!] Браузер Playwright не установился. Сайт откроется, но поиск может не работать.
  echo     Позже доустановить: .venv\Scripts\python.exe -m playwright install chromium
)

if not exist ".venv\Scripts\toursearch.exe" (
  echo [!] Установка завершилась с ошибкой - toursearch.exe не создан. Прерываю.
  echo.
  pause
  exit /b 1
)
echo [4/4] Python-часть установлена.
echo.

:envok
echo.
rem --- интерфейс: первая установка зависимостей (если нужно) + сборка ---
where npm >nul 2>&1 || goto :skipbuild
if not exist "frontend\package.json" goto :skipbuild
pushd frontend
if not exist "node_modules" (
  echo Первая установка интерфейса ^(npm install^) - пара минут ...
  call npm install
)
echo Обновляю интерфейс, это пара секунд...
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
rem --host 127.0.0.1 явно: чтобы случайная переменная окружения / правка не
rem повесила сервер на 0.0.0.0 и не открыла его в локальную сеть без TLS.
start "Tour Search (СЕРВЕР - не закрывать)" ".venv\Scripts\toursearch.exe" web --host 127.0.0.1 --port %PORT%
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
