$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = Join-Path $repoRoot "backend"
$frontend = Join-Path $repoRoot "frontend"

Write-Host "Cyber Interview Agent - main workspace"
Write-Host ""
Write-Host "Terminal 1 (backend, port 8000, default application data):"
Write-Host "  Remove-Item Env:CYBER_INTERVIEW_AGENT_DATA_DIR -ErrorAction SilentlyContinue"
Write-Host "  Set-Location '$backend'"
Write-Host "  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000"
Write-Host ""
Write-Host "Terminal 2 (frontend, port 5173):"
Write-Host "  `$env:CYBER_API_TARGET = 'http://127.0.0.1:8000'"
Write-Host "  Set-Location '$frontend'"
Write-Host "  pnpm dev -- --host 127.0.0.1 --port 5173"
Write-Host ""
Write-Host "Open http://127.0.0.1:5173"
