@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tour Search
echo ============================================
echo    Tour Search - запуск сайта
echo ============================================
echo.

rem --- проверка, что окружение установлено ---
if not exist ".venv\Scripts\toursearch.exe" (
  echo [!] Не найдено окружение .venv\Scripts\toursearch.exe
  echo     Похоже, проект ещё не установлен. См. инструкцию (первый запуск).
  echo.
  pause
  exit /b 1
)

rem --- обновление интерфейса до актуальной версии (если установлен Node) ---
rem   сервер отдаёт уже собранный frontend\dist; пересобираем, чтобы показать
rem   последние изменения (напр. площадку Travelata). Нет Node — не страшно,
rem   откроется ранее собранная версия.
where npm >nul 2>nul
if %errorlevel%==0 (
  if exist "frontend\package.json" (
    echo Обновляю интерфейс ^(npm run build^), это пара секунд...
    pushd frontend
    call npm run build
    popd
    echo Интерфейс обновлён.
    echo.
  )
) else (
  echo [i] Node/npm не найден - открою ранее собранную версию интерфейса.
  echo.
)

echo Запускаю сервер в отдельном окне...
start "Tour Search (СЕРВЕР - не закрывать)" ".venv\Scripts\toursearch.exe" web

echo Жду пару секунд, пока сервер поднимется...
timeout /t 4 /nobreak >nul

echo Открываю сайт в браузере: http://127.0.0.1:8000
start "" "http://127.0.0.1:8000"

echo.
echo ---------------------------------------------------------
echo  Сайт открыт: http://127.0.0.1:8000
echo  Открылось отдельное чёрное окно "Tour Search (СЕРВЕР)".
echo  ПОКА оно открыто - сайт работает.
echo  Чтобы ОСТАНОВИТЬ сайт - закройте то окно.
echo ---------------------------------------------------------
echo.
echo Это окно можно закрыть.
pause
