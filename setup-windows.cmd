@echo off
REM RAO Windows setup. Prepares the Docker Compose deployment only.
REM The full stack (PostgreSQL, Redis, API, solver worker, nginx-served SPA)
REM runs in Compose. No local Python, Node or database install is required.
setlocal EnableExtensions
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo [setup] Docker Desktop was not found on PATH.
  echo [setup] Install and start Docker Desktop, then rerun this script.
  exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
  echo [setup] Docker Compose v2 is not available. Update Docker Desktop.
  exit /b 1
)

if not exist "deploy\.env" (
  copy /y "deploy\.env.example" "deploy\.env" >nul
  echo [setup] Created deploy\.env from deploy\.env.example.
  echo [setup] Edit deploy\.env and set POSTGRES_PASSWORD before any public use.
) else (
  echo [setup] deploy\.env already exists, leaving it unchanged.
)

echo [setup] Validating deploy\docker-compose.yml ...
docker compose -f deploy\docker-compose.yml config >nul
if errorlevel 1 (
  echo [setup] Compose configuration is invalid.
  exit /b 1
)
echo [setup] Compose configuration is valid.
echo [setup] Next: start-windows.cmd
endlocal
exit /b 0
