@echo off
cd /d "%~dp0"
echo ==========================================
echo   FOCUS BUDDY
echo   AI-Powered Accountability Partner
echo ==========================================
echo.
echo Usage: buddy [command] [options]
echo   buddy web                    - Start web UI
echo   buddy start --goal "..."     - Start CLI session
echo   buddy provider list          - List providers
echo   buddy provider add ...       - Add provider
echo   buddy --help                 - Full help
echo.
echo Opening web UI...
start http://localhost:8765
python -m buddy web
