param(
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$Demo
)
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project virtual environment not found. See README.md.'
}
Set-Location -LiteralPath $projectRoot
$launchArgs = @('launch.py', '--port', "$Port")
if ($Demo) { $launchArgs += '--demo' }
& $pythonPath @launchArgs
