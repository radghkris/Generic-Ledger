@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo Updating the copy of the ledger in:
echo   %CD%
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo Git isn't installed on this computer, or isn't on PATH.
    echo Install it from https://git-scm.com/download/win then try again.
    echo.
    pause
    exit /b 1
)

git rev-parse --is-inside-work-tree >nul
if errorlevel 1 (
    echo.
    echo The folder above isn't a git clone, so there is nothing to update.
    echo Run update.bat from inside the folder that "git clone" created -
    echo the one that contains a hidden .git folder.
    echo.
    pause
    exit /b 1
)

set "_has_changes="
for /f "delims=" %%i in ('git status --porcelain') do set "_has_changes=1"
if defined _has_changes (
    echo You have local changes in this folder that aren't committed:
    echo.
    git status --short
    echo.
    set /p _confirm="Pull anyway? Uncommitted changes could be overwritten if they conflict (y/n): "
    if /i not "!_confirm!"=="y" (
        echo Skipped.
        pause
        exit /b 0
    )
)

echo Pulling the latest files from GitHub...
git pull
if errorlevel 1 (
    echo.
    echo The update failed - see the message above.
    pause
    exit /b 1
)

echo.
echo Up to date.
pause
