# Restore the workstation RTX PRO 6000's 600 W factory power limit.
# The K20 scan must already be complete. Run in elevated Windows PowerShell.
$ErrorActionPreference = 'Stop'

$periodicName = 'NvidiaGpuPowerLimit250W'
$logonName = 'ElevatiaGpuPowerLimit250'
$periodic = Get-ScheduledTask -TaskName $periodicName
$logon = Get-ScheduledTask -TaskName $logonName

if ($periodic.Actions.Count -ne 1 -or
    $periodic.Actions[0].Execute -ine 'C:\WINDOWS\system32\nvidia-smi.exe' -or
    $periodic.Actions[0].Arguments -ne '-pl 250') {
    throw 'Periodic task differs from the audited 250 W configuration.'
}
if ($logon.Actions.Count -ne 1 -or
    $logon.Actions[0].Execute -ine 'powershell.exe' -or
    $logon.Actions[0].Arguments -notmatch 'windows_set_gpu_power_limit.ps1' -or
    $logon.Actions[0].Arguments -notmatch '-TargetWatts 250') {
    throw 'Boot/logon task differs from the audited 250 W configuration.'
}

$backup = Join-Path $env:USERPROFILE ('gpu-power-task-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in @($periodicName, $logonName)) {
    Export-ScheduledTask -TaskName $name |
        Out-File -LiteralPath (Join-Path $backup ($name + '.xml')) -Encoding Unicode
}
Write-Output ('Backup: ' + $backup)

Disable-ScheduledTask -TaskName $periodicName | Out-Null
Disable-ScheduledTask -TaskName $logonName | Out-Null

& "$env:WINDIR\system32\nvidia-smi.exe" -i 0 -pl 600
if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi could not set the 600 W power limit.' }

foreach ($name in @($periodicName, $logonName)) {
    $task = Get-ScheduledTask -TaskName $name
    if ($task.State -ne 'Disabled') { throw ($name + ' did not become disabled.') }
    Write-Output ($name + ': ' + $task.State + '; original action ' + $task.Actions[0].Arguments)
}
& "$env:WINDIR\system32\nvidia-smi.exe" --query-gpu=name,power.limit,power.default_limit,power.max_limit --format=csv,noheader
if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi readback failed.' }
