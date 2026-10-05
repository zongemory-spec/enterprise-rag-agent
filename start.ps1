param([switch]$Real, [switch]$Semantic, [switch]$BuildIndex, [string]$ProviderEnvFile)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('run_server.py', '--port', '8006')
if ($Real) {
    if ($ProviderEnvFile) { $env:RAG_PROVIDER_ENV_FILE = $ProviderEnvFile }
    $arguments += '--real'
}
$ragPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $ragPython)) { $ragPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'Enterprise RAG Agent v3_1\.venv\Scripts\python.exe' }
if ($Semantic) { $arguments += '--semantic' }
if ($BuildIndex) {
    if (!$Semantic) { throw 'BuildIndex requires Semantic.' }
    & $ragPython 'sync_pg.py' '--real'
    if ($LASTEXITCODE -ne 0) { throw 'Index build failed.' }
    exit
}
& $ragPython @arguments
