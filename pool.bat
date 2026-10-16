@echo off
rem ===========================================================================
rem  ChatGPT Image Pool Kit - console launcher
rem
rem  IMPORTANT: this file must stay ASCII-only and use CRLF line endings.
rem  cmd.exe mis-parses non-ASCII bytes in batch files (it eats the leading
rem  characters of the next line), which makes commands silently fail.
rem  All Chinese/user-facing text is printed by the Python scripts instead.
rem
rem  Double-click  -> interactive menu (best for beginners)
rem  Command line  -> pool.bat <command> [args]
rem ===========================================================================
setlocal enabledelayedexpansion
rem Do not change the code page: inherit it (936 on Chinese Windows) so that
rem both Chinese paths and Chinese output render correctly.
cd /d "%~dp0"

rem NOTE: we deliberately do NOT guess "was this double-clicked?" -- a wrong
rem guess would hang scripted/agent calls. Instead we only pause on the two
rem paths a double-click user actually reaches (menu, missing Python).

call :find_python
set "S=%~dp0scripts"

rem Fail early with an actionable message if Python is missing.
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found or not usable: "%PY%"
    echo.
    echo  Fix: install Python 3.11 or 3.12 from python.org and CHECK "Add python.exe to PATH",
    echo       then close this window and double-click pool.bat again.
    echo  Docs: docs  -  read the newbie guide -- docs\00-xin-shou-bi-du.md
    echo.
    pause
    goto :end
)

if "%~1"=="" goto :menu
if /I "%~1"=="menu"   goto :menu
if /I "%~1"=="start"  goto :start
if /I "%~1"=="stop"   goto :stop
if /I "%~1"=="status" goto :status
if /I "%~1"=="doctor" goto :doctor
if /I "%~1"=="setup"  goto :setup
if /I "%~1"=="test"   goto :test
if /I "%~1"=="reset"  goto :reset
if /I "%~1"=="install-skill" goto :installskill
if /I "%~1"=="patch"  goto :patch
if /I "%~1"=="warm"   goto :warm
if /I "%~1"=="sync"   goto :sync
if /I "%~1"=="gen"    goto :gen
if /I "%~1"=="batch"  goto :batch
if /I "%~1"=="import" goto :import
if /I "%~1"=="logs"   goto :logs
if /I "%~1"=="help"   goto :help
if /I "%~1"=="-h"     goto :help
if /I "%~1"=="--help" goto :help

echo [ERROR] Unknown command: %~1
goto :help

rem ---------------------------------------------------------------------------
rem Locate a Python interpreter: FPB_ROOT venv, then sibling fpbrowser2api, then PATH
rem ---------------------------------------------------------------------------
:find_python
set "PY="
if defined FPB_ROOT (
    if exist "%FPB_ROOT%\.venv\Scripts\python.exe" set "PY=%FPB_ROOT%\.venv\Scripts\python.exe"
)
if not defined PY if exist "%~dp0..\fpbrowser2api\.venv\Scripts\python.exe" set "PY=%~dp0..\fpbrowser2api\.venv\Scripts\python.exe"
if not defined PY if exist "D:\fpbrowser2api\.venv\Scripts\python.exe" set "PY=D:\fpbrowser2api\.venv\Scripts\python.exe"
if not defined PY if exist "C:\fpbrowser2api\.venv\Scripts\python.exe" set "PY=C:\fpbrowser2api\.venv\Scripts\python.exe"
if not defined PY set "PY=python"
exit /b 0

:menu
"%PY%" "%S%\menu.py"
if errorlevel 1 pause
goto :end

:start
"%PY%" "%S%\start_all.py" %2 %3 %4 %5 %6
goto :end

:stop
"%PY%" "%S%\stop_all.py" %2 %3 %4 %5 %6
goto :end

:status
"%PY%" "%S%\status_all.py" %2 %3 %4 %5 %6
goto :end

:doctor
"%PY%" "%S%\doctor.py" %2 %3 %4 %5 %6
goto :end

:setup
"%PY%" "%S%\setup_pool.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :end

:test
"%PY%" "%S%\selftest.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :end

:reset
"%PY%" "%S%\reset_pool.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :end

:installskill
"%PY%" "%S%\install_skill.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :end

:patch
"%PY%" "%S%\apply_patches.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :end

:warm
"%PY%" "%S%\warmup_windows.py" %2 %3 %4 %5 %6
goto :end

:sync
"%PY%" "%S%\sync_vb_pool.py" %2 %3 %4 %5 %6
goto :end

rem ---------------------------------------------------------------------------
rem  gen / batch / import: collect every argument after the subcommand and
rem  re-quote each one so that values containing spaces survive.
rem  NOTE: the loop must be inlined here. Inside a `call :label` subroutine,
rem  %1 refers to the subroutine's own (empty) arguments, not the script's.
rem ---------------------------------------------------------------------------
:gen
shift
set "ARGS="
:gen_loop
if "%~1"=="" goto :gen_run
set ARGS=%ARGS% "%~1"
shift
goto :gen_loop
:gen_run
"%PY%" "%S%\gen_image.py" %ARGS%
goto :end

:batch
shift
set "ARGS="
:batch_loop
if "%~1"=="" goto :batch_run
set ARGS=%ARGS% "%~1"
shift
goto :batch_loop
:batch_run
"%PY%" "%S%\batch_gen.py" %ARGS%
goto :end

:import
shift
set "ARGS="
:import_loop
if "%~1"=="" goto :import_run
set ARGS=%ARGS% "%~1"
shift
goto :import_loop
:import_run
"%PY%" "%S%\import_chatgpt_tokens.py" %ARGS%
goto :end

:logs
echo [INFO] Python: %PY%
"%PY%" "%S%\tail_logs.py" %2 %3 %4 %5 %6
goto :end

:help
echo.
echo   ChatGPT Image Pool Kit - console
echo   ============================================================
echo   FIRST TIME
echo     pool.bat setup            one-click install (deps/patch/config/provision)
echo     pool.bat test             end-to-end check (really generates one image)
echo   DAILY
echo     pool.bat start            start services (background, no window)
echo     pool.bat status           pool dashboard (services / windows / tokens)
echo     pool.bat gen "PROMPT" -o out.png [--ratio 1:1] [--res 1k] [--style ...]
echo     pool.bat gen --prompt-file prompt.txt -o out.png   (prompt with punctuation)
echo     pool.bat batch prompts.txt --outdir out --concurrency 3
echo   POOL
echo     pool.bat import accounts.txt [--yes] [--only 1]
echo     pool.bat warm             warm up window pool (run once for a new pool)
echo     pool.bat sync             sync windows and bind task pool
echo   TOOLS
echo     pool.bat doctor           full environment self-check
echo     pool.bat reset            clean up (keeps accounts/tokens)
echo     pool.bat patch            apply/revert upstream patches (no git needed)
echo     pool.bat install-skill    install into your AI agent skills dir
echo     pool.bat logs             tail service logs
echo     pool.bat stop             stop services + close fingerprint windows
echo     pool.bat                  (no args) interactive menu
echo   ============================================================
echo   Python: %PY%
echo   See README.md / docs/ for Chinese documentation.
echo.
goto :end

:end
rem Keep the window open only when the user pressed a key (pause already done above).
exit /b %ERRORLEVEL%
