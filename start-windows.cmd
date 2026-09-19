@echo off
REM RAO Windows start. Thin wrapper over `make up` for the Compose stack.
setlocal EnableExtensions
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo [start] Docker Desktop was not found on PATH.
  exit /b 1
)

if not exist "deploy\.env" (
  echo [start] deploy\.env is missing. Run setup-windows.cmd first.
  exit /b 1
)

echo [start] docker compose -f deploy\docker-compose.yml up --build -d
docker compose -f deploy\docker-compose.yml up --build -d
if errorlevel 1 (
  echo [start] Failed to start the stack.
  exit /b 1
)

echo [start] Control board  : http://localhost:5173
echo [start] API docs       : http://localhost:8000/docs
echo [start] Follow logs    : docker compose -f deploy\docker-compose.yml logs -f --tail=100
echo [start] Stop the stack : docker compose -f deploy\docker-compose.yml down
endlocal
exit /b 0
