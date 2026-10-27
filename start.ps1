# AgenticDB Quick Launch PowerShell Script
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "              Starting AgenticDB Platform               " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Seed demo database
Write-Host "`n[1/3] Ensuring demo database is seeded..." -ForegroundColor Yellow
python "$scriptDir\datasets\scripts\seed_demo_data.py"

# 2. Launch Backend
Write-Host "`n[2/3] Starting FastAPI Backend on http://localhost:8000..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$scriptDir\backend'; uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

# 3. Launch Frontend
Write-Host "`n[3/3] Starting React Vite Frontend on http://localhost:5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$scriptDir\frontend'; npm run dev"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "AgenticDB is now running!" -ForegroundColor Green
Write-Host "• Frontend UI:     http://localhost:5173" -ForegroundColor White
Write-Host "• Backend API:     http://localhost:8000" -ForegroundColor White
Write-Host "• Interactive Docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
