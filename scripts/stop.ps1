# Encerra o servidor do TokenBar (o processo que escuta na porta configurada).
$port = if ($env:TOKENBAR_PORT) { [int]$env:TOKENBAR_PORT } else { 7878 }
$conns = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) { Write-Output "TokenBar não está rodando na porta $port."; exit 0 }
foreach ($c in $conns) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match '^pythonw?$') {
        Stop-Process -Id $p.Id -Confirm:$false
        Write-Output "TokenBar encerrado (PID $($p.Id))."
    } else {
        Write-Output "A porta $port está com outro programa ($($p.ProcessName)); não mexi."
    }
}
