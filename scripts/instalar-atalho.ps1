# Cria o atalho "TokenBar" no Menu Iniciar e na Área de Trabalho.
#   -AoIniciar     também inicia o TokenBar (só o ícone) quando você entra no Windows
#   -Remover       apaga todos os atalhos criados por este script
param([switch]$AoIniciar, [switch]$Remover)

$root  = Split-Path -Parent $PSScriptRoot
$icon  = Join-Path $root 'web\assets\tokenbar.ico'
$pyw   = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
$shell = New-Object -ComObject WScript.Shell

$desktop = [Environment]::GetFolderPath('Desktop')
$menu    = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
$startup = [Environment]::GetFolderPath('Startup')

if ($Remover) {
    foreach ($dir in @($desktop, $menu, $startup)) {
        $p = Join-Path $dir 'TokenBar.lnk'
        if (Test-Path $p) { Remove-Item $p -Confirm:$false; Write-Output "Removido: $p" }
    }
    exit 0
}
if (-not $pyw) { throw 'pythonw.exe não encontrado. Instale o Python 3.10+.' }

function New-Atalho($dir, $argumentos) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'TokenBar.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = $argumentos
    $lnk.WorkingDirectory = $root
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Description = 'TokenBar: limites do Claude e do Codex'
    $lnk.Save()
    Write-Output "Atalho criado em $dir"
}

New-Atalho $desktop '-m tokenbar --show'
New-Atalho $menu    '-m tokenbar --show'
if ($AoIniciar) { New-Atalho $startup '-m tokenbar' }
