# Cria o atalho "Breath" no Menu Iniciar e na Área de Trabalho.
#   -AoIniciar     também inicia o Breath (só o ícone) quando você entra no Windows
#   -Remover       apaga todos os atalhos criados por este script
param([switch]$AoIniciar, [switch]$Remover)

$root  = Split-Path -Parent $PSScriptRoot
$icon  = Join-Path $root 'web\assets\breath.ico'
$pyw   = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
$shell = New-Object -ComObject WScript.Shell

$desktop = [Environment]::GetFolderPath('Desktop')
$menu    = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
$startup = [Environment]::GetFolderPath('Startup')

# Atalhos de versões antigas (TokenBar, Fôlego) sempre saem.
foreach ($dir in @($desktop, $menu, $startup)) {
    foreach ($nome in @('TokenBar.lnk', 'Fôlego.lnk')) {
        $old = Join-Path $dir $nome
        if (Test-Path $old) { Remove-Item $old -Confirm:$false; Write-Output "Removido (antigo): $old" }
    }
}
if ($Remover) {
    foreach ($dir in @($desktop, $menu, $startup)) {
        $p = Join-Path $dir 'Breath.lnk'
        if (Test-Path $p) { Remove-Item $p -Confirm:$false; Write-Output "Removido: $p" }
    }
    exit 0
}
if (-not $pyw) { throw 'pythonw.exe não encontrado. Instale o Python 3.10+.' }

function New-Atalho($dir, $argumentos) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'Breath.lnk'))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = $argumentos
    $lnk.WorkingDirectory = $root
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Description = 'Breath: limites do Claude e do Codex'
    $lnk.Save()
    Write-Output "Atalho criado em $dir"
}

New-Atalho $desktop '-m breath --show'
New-Atalho $menu    '-m breath --show'
if ($AoIniciar) { New-Atalho $startup '-m breath' }
