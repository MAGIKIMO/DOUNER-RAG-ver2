$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    docker compose up -d --build app
    if ($LASTEXITCODE -ne 0) { throw 'App build failed' }
    docker compose exec -T app python -m app.crawl_campus_life --days 365 --max-pages 30
    if ($LASTEXITCODE -ne 0) { throw 'Campus crawl failed' }
    docker compose exec -T app python -m app.ingest_notices_to_context
    if ($LASTEXITCODE -ne 0) { throw 'Chunk ingestion failed' }
    docker compose exec -T app python -m app.ingest_context_to_chroma
    if ($LASTEXITCODE -ne 0) { throw 'Vector ingestion failed' }
    Write-Host 'Pipeline completed. Check crawl output for failed/partial sources.'
} finally {
    Pop-Location
}
