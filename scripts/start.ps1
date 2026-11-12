# Inicia o TokenBar em segundo plano (se ainda não estiver rodando) e abre o painel
# numa janela própria do Edge, sem barra de endereço.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = if ($env:TOKENBAR_PORT) { $env:TOKENBAR_PORT } else { '7878' }
$url  = "http://127.0.0.1:$port/"

function Test-TokenBar {
    try {
        Invoke-WebRequest "${url}api/health" -Headers @{ 'X-TokenBar' = '1' } -UseBasicParsing -TimeoutSec 1 | Out-Null
        return $true
    } catch { return $false }
}

if (-not (Test-TokenBar)) {
    $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $pyw) { $pyw = (Get-Command python.exe).Source }
    Start-Process -FilePath $pyw -ArgumentList '-m', 'tokenbar' -WorkingDirectory $root -WindowStyle Hidden
    for ($i = 0; $i -lt 25 -and -not (Test-TokenBar); $i++) { Start-Sleep -Milliseconds 200 }
}

$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=$url", '--window-size=1120,860'
} else {
    Start-Process $url
}
