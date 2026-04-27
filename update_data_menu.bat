@echo off
setlocal
cd /d "%~dp0"

:menu
cls
echo ========================================
echo   FinMind Data Update
echo ========================================
echo.
echo   1. Stock Price
echo   2. Stock Price Adj
echo   3. CB Daily Price
echo   4. CB Basic Data
echo   5. Update All
echo   6. DB Status
echo   0. Exit
echo.
set /p choice=Select:

if "%choice%"=="1" (
    set category=stock
    goto run
)
if "%choice%"=="2" (
    set category=stock_adj
    goto run
)
if "%choice%"=="3" (
    set category=cb_daily
    goto run
)
if "%choice%"=="4" (
    set category=cb_basic
    goto run
)
if "%choice%"=="5" (
    set category=all
    goto run
)
if "%choice%"=="6" (
    set category=status
    goto run
)
if "%choice%"=="0" exit /b 0

echo.
echo Invalid option.
pause
goto menu

:run
cls
python update_data.py %category%
echo.
pause
goto menu
