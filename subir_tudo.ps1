# subir_tudo.ps1
# Sobe o n8n e a API Flask juntos, cada um numa janela separada do PowerShell.
# Salve este arquivo na RAIZ do projeto (mesma pasta onde está a pasta ".venv"),
# ao lado do README.md.

$raiz = $PSScriptRoot

Write-Host "Subindo n8n..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npx n8n"

Write-Host "Subindo API Flask..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$raiz'; .\.venv\Scripts\Activate.ps1; flask --app api.app run"

Write-Host ""
Write-Host "Duas janelas novas foram abertas:" -ForegroundColor Green
Write-Host "  1) n8n        -> http://localhost:5678"
Write-Host "  2) API Flask  -> http://localhost:5000"
Write-Host ""
Write-Host "Aguarde alguns segundos para os dois iniciarem por completo." -ForegroundColor Yellow
