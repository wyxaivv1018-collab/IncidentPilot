param([switch]$Live, [int]$Port = 4180)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
# Read external Windows environment only. Never save or print the credential.
if (-not $env:NEBIUS_API_KEY) {
    $env:NEBIUS_API_KEY = [Environment]::GetEnvironmentVariable('NEBIUS_API_KEY', 'User')
}
if (-not $env:NEBIUS_API_KEY) {
    $env:NEBIUS_API_KEY = [Environment]::GetEnvironmentVariable('NEBIUS_API_KEY', 'Machine')
}
$runArgs = @('run', '--frozen', '--with-requirements', 'docs/nebius/runtime-requirements.txt', 'python', 'scripts/run_nebius.py', 'serve', '--port', "$Port")
if ($Live) { $runArgs += '--live' }
& uv @runArgs
exit $LASTEXITCODE
