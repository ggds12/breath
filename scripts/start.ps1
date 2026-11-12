# Inicia o TokenBar na área de notificação (ícones ocultos) e abre a janelinha.
# Se ele já estiver rodando, abre o painel completo no navegador.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = if ($env:TOKENBAR_PORT) { $env:TOKENBAR_PORT } else { '7878' }
$url  = "http://127.0.0.1:$port/"

try {
    Invoke-WebRequest "${url}api/health" -Headers @{ 'X-TokenBar' = '1' } -UseBasicParsing -TimeoutSec 1 | Out-Null
    Start-Process $url
    exit 0
} catch { }

$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) { throw 'pythonw.exe não encontrado. Instale o Python 3.10+.' }
Start-Process -FilePath $pyw -ArgumentList '-m', 'tokenbar', '--show' -WorkingDirectory $root
