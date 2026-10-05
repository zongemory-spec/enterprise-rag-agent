param([switch]$Real, [string]$ProviderEnvFile)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('run_server.py', '--port', '8004')
if ($Real) {
    if ($ProviderEnvFile) { $env:RAG_PROVIDER_ENV_FILE = $ProviderEnvFile }
    $arguments += '--real'
}
$ragPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $ragPython)) { $ragPython = Join-Path (Split-Path $PSScriptRoot -Parent) 'Enterprise RAG Agent v3_1\.venv\Scripts\python.exe' }
& $ragPython @arguments
