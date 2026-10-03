param([switch]$Real)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('run_server.py', '--port', '8003')
if ($Real) { $arguments += '--real' }
& '.\.venv\Scripts\python.exe' @arguments
