param(
    [ValidateSet('chrome', 'msedge', 'chromium')][string]$BrowserChannel = 'chrome',
    [switch]$SkipInstall,
    [switch]$SkipServiceStart
)
$ErrorActionPreference = 'Stop'
$repoDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoDir '.venv-e2e/Scripts/python.exe'
$cacheDir = Join-Path $repoDir '.e2e-cache'
$artifactsDir = Join-Path $repoDir ('test-results/e2e-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$envKeys = @('TEMP','TMP','PIP_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH','PLAYWRIGHT_SKIP_BROWSER_GC',
             'PYBATGYM_E2E','PYBATGYM_E2E_RUNS_DIR','PYTHONDONTWRITEBYTECODE')
$savedEnv = @{}
foreach ($key in $envKeys) { $savedEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
Push-Location $repoDir
try {
    New-Item -ItemType Directory -Force $artifactsDir, "$cacheDir/tmp", "$cacheDir/pip" | Out-Null
    $env:TEMP = "$cacheDir/tmp"
    $env:TMP = "$cacheDir/tmp"
    $env:PIP_CACHE_DIR = "$cacheDir/pip"
    $env:PLAYWRIGHT_BROWSERS_PATH = "$cacheDir/browsers"
    $env:PLAYWRIGHT_SKIP_BROWSER_GC = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYBATGYM_E2E = '1'
    $env:PYBATGYM_E2E_RUNS_DIR = Join-Path $repoDir 'runs/e2e'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        & python -m venv (Join-Path $repoDir '.venv-e2e')
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create .venv-e2e. Python >=3.10 is required.' }
    }
    if (-not $SkipInstall) {
        & $pythonExe -m pip install -r tests/e2e/requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Unable to install E2E test dependencies.' }
    }
    if (-not $SkipServiceStart) {
        & docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml up -d --no-deps --no-build playground-e2e
        if ($LASTEXITCODE -ne 0) { throw 'Unable to start only the isolated PyBatGym E2E service.' }
    }
    $healthUrl = 'http://127.0.0.1:5051/pun/dev/pybatgym_playground/playground/health'
    $deadline = (Get-Date).AddSeconds(120)
    $healthy = $false
    do {
        try {
            $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
            $healthy = ($health.e2e_workspace -eq $true -and $health.execution_mode -eq 'local')
        } catch { $healthy = $false }
        if (-not $healthy) { Start-Sleep -Seconds 1 }
    } until ($healthy -or (Get-Date) -gt $deadline)
    if (-not $healthy) { throw 'Isolated E2E service is not ready; normal user workspace will not be used.' }
    & $pythonExe -m pip freeze | Set-Content -LiteralPath "$artifactsDir/requirements-resolved.txt" -Encoding utf8
    $pytestArgs = @('-m','pytest','tests/e2e','-q','-p','no:cacheprovider',
        '--e2e-url','http://127.0.0.1:5051','--e2e-channel',$BrowserChannel,
        '--e2e-artifacts',$artifactsDir,'--junitxml',"$artifactsDir/junit.xml")
    & $pythonExe @pytestArgs 2>&1 | Tee-Object -FilePath "$artifactsDir/console.log"
    $testExit = $LASTEXITCODE
    Write-Host "E2E report: $artifactsDir"
    exit $testExit
} finally {
    foreach ($key in $envKeys) { [Environment]::SetEnvironmentVariable($key, $savedEnv[$key], 'Process') }
    Pop-Location
}
