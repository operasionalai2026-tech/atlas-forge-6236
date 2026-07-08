@echo off
REM Wrapper auto-restart: kalau bot.js crash/keluar, tunggu 5 detik lalu jalan lagi.
REM Dipanggil oleh Windows Task Scheduler saat logon (lihat DEPLOY.md / instruksi setup).
cd /d "%~dp0"
:loop
echo [%date% %time%] Menjalankan WhatsApp daemon...
node bot.js
echo [%date% %time%] Daemon berhenti (exit code %errorlevel%) — restart dalam 5 detik...
timeout /t 5 /nobreak >nul
goto loop
