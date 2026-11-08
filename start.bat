@echo off
chcp 65001 >nul
title Comprador IA — Guerra das IAs / Hackathon Digitaly 03
cls

echo ==============================================================
echo       COMPRADOR IA — GUERRA DAS IAs (HACKATHON DIGITALY 03)
echo ==============================================================
echo.
echo Iniciando servidores locais...
echo.

:: 1. Iniciar Backend (FastAPI na porta 8000)
echo [1/2] Subindo Backend FastAPI na porta 8000...
start "Backend - FastAPI :8000" cmd /k "cd /d "%~dp0backend" && if exist .venv\Scripts\activate.bat (call .venv\Scripts\activate.bat) && uvicorn app.main:app --reload --port 8000"

:: 2. Iniciar Frontend (Next.js na porta 3000)
echo [2/2] Subindo Frontend Next.js na porta 3000...
start "Frontend - Next.js :3000" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ==============================================================
echo Servidores inicializados em janelas dedicadas!
echo.
echo   * Frontend (Kanban Cyberpunk): http://localhost:3000
echo   * Backend (FastAPI / Swagger): http://127.0.0.1:8000/docs
echo   * Roteiro da Banca:             Consulte o arquivo DEMO.md
echo ==============================================================
echo.
pause
