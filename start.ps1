param([switch]$Real, [switch]$Semantic, [switch]$BuildIndex, [string]$ProviderEnvFile, [string]$EnvFile)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('run_server.py', '--port', '8006')
if ($Real) {
    if ($ProviderEnvFile) { $env:RAG_PROVIDER_ENV_FILE = $ProviderEnvFile }
    $arguments += '--real'
}
$ragPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $ragPython)) { throw 'Create .venv and install requirements.lock first; see README.md.' }
if ($EnvFile) { $arguments += @('--env-file', $EnvFile) }
if ($Semantic) { $arguments += '--semantic' }
if ($BuildIndex) {
    if (!$Semantic) { throw 'BuildIndex requires Semantic.' }
    $indexArguments = @('sync_pg.py', '--real')
    if ($EnvFile) { $indexArguments += @('--env-file', $EnvFile) }
    & $ragPython @indexArguments
    if ($LASTEXITCODE -ne 0) { throw 'Index build failed.' }
    exit
}
& $ragPython @arguments
