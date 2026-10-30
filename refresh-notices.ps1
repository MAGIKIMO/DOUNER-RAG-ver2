param(
    [ValidateRange(1,3650)][int]$Days = 30,
    [ValidateRange(1,100)][int]$MaxPages = 10,
    [switch]$ExamsOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory ('refresh-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
# Avoid overlapping this script. Python also coordinates with manual jobs via MySQL.
$guard = $null
$transcript = $false
try {
    $guard = [System.IO.File]::Open((Join-Path $logDirectory 'refresh.lock.log'), 'OpenOrCreate', 'ReadWrite', 'None')
    Start-Transcript -Path $logPath | Out-Null
    $transcript = $true
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running or is inaccessible.' }
    $running = @(docker compose ps --status running --services)
    if ($LASTEXITCODE -ne 0 -or $running -notcontains 'app') { throw 'Start the app with docker compose up -d first.' }
    if (-not $ExamsOnly) {
        docker compose exec -T app python -m app.crawl_public --boards-only --days $Days --max-pages $MaxPages
        if ($LASTEXITCODE -ne 0) { throw 'Notice refresh failed; see log.' }
    }
    $koreaNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Korea Standard Time')
    $semester = if ($koreaNow.Month -lt 8) { 1 } else { 2 }
    # Exam updater includes attachment extraction and both index stages.
    docker compose exec -T app python -m app.update_exams --year $koreaNow.Year --term $semester --max-pages $MaxPages
    if ($LASTEXITCODE -ne 0) { throw 'Exam/index refresh failed; see log.' }
    Write-Host 'Refresh pipeline finished. Review per-source failures and exam_coverage in this log.'
    Write-Host "Log: $logPath"
} catch {
    Write-Host ('Refresh did not finish: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    if ($guard) { $guard.Dispose() }
}
