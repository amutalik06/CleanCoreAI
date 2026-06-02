@echo off
echo Starting CleanCore AI...

echo Starting Backend API (FastAPI)...
start "CleanCore Backend" cmd /k "cd backend && py -3.12 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude \"*.log\" --reload-exclude \"*.err\""

echo Starting Frontend UI (React/Vite)...
start "CleanCore Frontend" cmd /k "cd frontend && npm run dev"

echo CleanCore AI is starting! 
echo The frontend will be available at http://localhost:5173
echo The backend API will be available at http://localhost:8000
