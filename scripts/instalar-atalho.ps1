# Cria um atalho "TokenBar" na Área de Trabalho e no Menu Iniciar.
# Use -AoIniciar para também abrir o TokenBar quando o Windows iniciar.
param([switch]$AoIniciar)

$root   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'start.ps1'
$icon   = Join-Path $root 'web\assets\tokenbar.ico'
$shell  = New-Object -ComObject WScript.Shell

$destinos = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs')
)
if ($AoIniciar) { $destinos += [Environment]::GetFolderPath('Startup') }

foreach ($dir in $destinos) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'TokenBar.lnk'))
    $lnk.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
    $lnk.WorkingDirectory = $root
    $lnk.WindowStyle = 7
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Description = 'TokenBar — limites do Claude e do Codex'
    $lnk.Save()
    Write-Output "Atalho criado em $dir"
}
