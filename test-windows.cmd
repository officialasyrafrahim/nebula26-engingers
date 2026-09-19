@echo off
REM RAO Windows test. Thin wrapper over `make features-validate`, `make lint`
REM and `make test`. The backend venv must already exist.
setlocal EnableExtensions
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [test] Python was not found on PATH.
  exit /b 1
)

echo [test] python scripts\features.py validate
python scripts\features.py validate
if errorlevel 1 goto :fail

if not exist "backend\.venv\Scripts\python.exe" (
  echo [test] backend\.venv is missing. Create it first:
  echo        python -m venv backend\.venv
  echo        backend\.venv\Scripts\python -m pip install -e "backend[dev,solver,postgres]"
  goto :fail
)

pushd backend
echo [test] .venv\Scripts\python -m ruff check app tests
".venv\Scripts\python.exe" -m ruff check app tests
if errorlevel 1 (
  popd
  goto :fail
)
echo [test] .venv\Scripts\python -m pytest -q
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo [test] All checks passed.
endlocal
exit /b 0

:fail
echo [test] Checks failed.
endlocal
exit /b 1
