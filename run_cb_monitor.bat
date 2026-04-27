@echo off
chcp 65001 > nul
setlocal

cd /d "%~dp0"

echo Updating Taiwan CB Monitor...
echo.

python update_data.py cb_daily
if errorlevel 1 (
    echo.
    echo CB daily data update failed. Please check the error message above.
    pause
    exit /b 1
)

python update_data.py cb_basic
if errorlevel 1 (
    echo.
    echo CB database update failed. Please check the error message above.
    pause
    exit /b 1
)

python cb_index.py
if errorlevel 1 (
    echo.
    echo Update failed. Please check the error message above.
    pause
    exit /b 1
)

echo.
echo Opening dashboard...
start "" "%~dp0output\cb_indices.html"

endlocal
