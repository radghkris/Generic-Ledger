@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".git" (
    echo This folder isn't a clone of the repo yet.
    echo Clone it first, then run this script from inside that folder.
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

echo.
echo Up to date.
pause
