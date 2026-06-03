@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tour Search
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
popd
echo Интерфейс обновлён.
:skipbuild
echo.
echo Запускаю сервер в отдельном окне...
start "Tour Search (СЕРВЕР - не закрывать)" ".venv\Scripts\toursearch.exe" web
echo Жду пару секунд, пока сервер поднимется...
timeout /t 4 /nobreak >nul
echo Открываю сайт в браузере: http://127.0.0.1:8000
start "" "http://127.0.0.1:8000"
echo.
echo ---------------------------------------------------------
echo  Сайт открыт: http://127.0.0.1:8000
echo  Открылось отдельное чёрное окно сервера.
echo  ПОКА оно открыто - сайт работает.
echo  Чтобы ОСТАНОВИТЬ сайт - закройте то окно.
echo ---------------------------------------------------------
echo.
echo Это окно можно закрыть.
pause
