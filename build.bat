@echo off
rem Сборка архива для раздачи: dist\model-picker.zip (из последнего коммита, без служебных файлов гита).
rem Запуск: двойной клик или build.bat в этой папке. Проверка плагина выполняется, если найден claude.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where git >nul 2>nul || (echo [ОШИБКА] git не найден в PATH & goto :fail)

git status --porcelain > "%TEMP%\mp_status.txt"
for %%A in ("%TEMP%\mp_status.txt") do if %%~zA GTR 0 (
  echo [ВНИМАНИЕ] Есть незакоммиченные изменения - в архив попадёт только последний коммит:
  type "%TEMP%\mp_status.txt"
  echo.
)
del "%TEMP%\mp_status.txt" >nul 2>nul

rem --- Проверка плагина (необязательно) ---
set "CLAUDE="
where claude >nul 2>nul && set "CLAUDE=claude"
if not defined CLAUDE (
  for /f "delims=" %%F in ('dir /b /s /o-d "%APPDATA%\Claude\claude-code\claude.exe" 2^>nul') do if not defined CLAUDE set "CLAUDE=%%F"
)
if defined CLAUDE (
  echo Проверка плагина...
  "%CLAUDE%" plugin validate "%~dp0." || (echo [ОШИБКА] Проверка не пройдена & goto :fail)
) else (
  echo [ПРОПУСК] claude не найден - проверка плагина пропущена.
)

rem --- Сборка архива ---
if not exist dist mkdir dist
if exist dist\model-picker.zip del dist\model-picker.zip
git archive --format=zip --prefix=model-picker/ -o dist\model-picker.zip HEAD || (echo [ОШИБКА] git archive не удался & goto :fail)

echo.
echo Готово: %~dp0dist\model-picker.zip
if "%1"=="" pause
exit /b 0

:fail
if "%1"=="" pause
exit /b 1
