$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "RigPilot environment not found at $python. Run the complete AI Hub setup first."
    exit 1
}

$env:PYTHONPATH = Join-Path $projectRoot 'src'

& $python -m unittest discover -s (Join-Path $projectRoot 'tests') -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -m ruff check $projectRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python -c "import rigpilot; print(f'RigPilot {rigpilot.__version__} import: PASS')"
exit $LASTEXITCODE
