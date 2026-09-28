$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose up -d --build app
if ($LASTEXITCODE -ne 0) { throw 'Docker build/start failed' }
docker compose exec -T app python -m app.update_exams
if ($LASTEXITCODE -ne 0) { throw 'Exam refresh failed; see output above' }
Write-Host 'Exam notice, attachment and search index refresh completed.'
