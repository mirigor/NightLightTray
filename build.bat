@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Не найден Python проекта: .venv\Scripts\python.exe
    exit /b 1
)
if not exist "tools\wnl.exe" (
    echo Не найден tools\wnl.exe. Сначала соберите win-nightlight-cli.
    exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)"
if errorlevel 1 (
    echo Для сборки требуется Python 3.10.
    exit /b 1
)
set "DIST_DIR=."
if not "%~1"=="" set "DIST_DIR=%~1"
".venv\Scripts\python.exe" tools\make_ico.py
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile --distpath "%DIST_DIR%" --specpath "%CD%\build" --workpath "%CD%\build" --name NightLightTray --icon "%CD%\resources\moon.ico" --add-data "%CD%\resources;resources" --add-binary "%CD%\tools\wnl.exe;tools" --add-data "%CD%\tools\WNL_LICENSE.txt;tools" --add-data "%CD%\tools\WNL_SOURCE.txt;tools" "%CD%\main.py"
if errorlevel 1 exit /b %errorlevel%
echo Готово: %DIST_DIR%\NightLightTray.exe
