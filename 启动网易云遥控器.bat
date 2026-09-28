@echo off
title NetEase Music Controller
cd /d "%~dp0"
"C:\Program Files\Python39\python.exe" server.py
if errorlevel 1 pause
