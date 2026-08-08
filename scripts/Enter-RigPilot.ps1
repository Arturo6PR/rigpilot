$projectRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $projectRoot '.venv'
$python = Join-Path $venvRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'RigPilot environment is missing. Run the complete AI Hub setup first.'
}

$env:Path = "$(Join-Path $venvRoot 'Scripts');$env:Path"
$env:VIRTUAL_ENV = $venvRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
Set-Location -LiteralPath $projectRoot

Write-Host 'RigPilot environment ready.' -ForegroundColor Green
& $python --version
Write-Host 'Run checks with: .\scripts\Test-RigPilot.ps1'
