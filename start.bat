@echo off
echo ========================================================
echo               Starting AgenticDB Platform               
echo ========================================================

echo.
echo [1/3] Checking demo database and sample data...
cd /d "%~dp0"
python datasets\scripts\seed_demo_data.py

echo.
echo [2/3] Launching FastAPI Backend on http://localhost:8000...
start "AgenticDB Backend" cmd /k "cd /d "%~dp0backend" && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo.
echo [3/3] Launching React Vite Frontend on http://localhost:5173...
start "AgenticDB Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ========================================================
echo AgenticDB is now running!
echo - Frontend UI: http://localhost:5173
echo - Backend API: http://localhost:8000
echo - Swagger Docs: http://localhost:8000/docs
echo ========================================================
