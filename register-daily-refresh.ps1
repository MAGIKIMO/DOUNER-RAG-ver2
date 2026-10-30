param([ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')][string]$At = '07:00')
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'refresh-notices.ps1'
if (-not (Test-Path -LiteralPath $script)) { throw 'refresh-notices.ps1 is missing.' }
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $script + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Douner-Daily-Refresh' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Description 'Refresh public notices and midterm documents for douner.' -Force | Out-Null
Write-Host "Registered Douner-Daily-Refresh at $At (Windows local time). Requires login and Docker Desktop running."
