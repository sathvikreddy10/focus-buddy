Set-Location $PSScriptRoot
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   FOCUS BUDDY" -ForegroundColor Green
Write-Host "   AI-Powered Accountability Partner" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Starting web UI..." -ForegroundColor Yellow
Start-Process "http://localhost:8765"
python -m buddy web
