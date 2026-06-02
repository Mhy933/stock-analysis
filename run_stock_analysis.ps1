$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Load-DotEnv {
    param([string]$Path)

    if (!(Test-Path $Path)) {
        return
    }

    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (!$line -or $line.StartsWith("#") -or !$line.Contains("=")) {
            return
        }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")

        if ($key -and !(Test-Path "Env:\$key")) {
            Set-Item -Path "Env:\$key" -Value $value
        }
    }
}

Write-Host ""
Write-Host "=== Stock Analysis Launcher ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host ""

Load-DotEnv -Path (Join-Path $ProjectRoot ".env")

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $ProjectRoot "requirements.txt"

if (!(Test-Path $VenvPython)) {
    Write-Host "[Setup] Creating local Python virtual environment ..." -ForegroundColor Yellow
    python -m venv (Join-Path $ProjectRoot ".venv")
}

if (!(Test-Path $VenvPython)) {
    Write-Host "[X] Virtual environment was not created. Please check whether Python is installed correctly." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "[Setup] Installing or updating Python dependencies ..." -ForegroundColor Yellow
& $VenvPython -m pip install -r $Requirements

$code = Read-Host "Enter 6-digit A-share stock code, for example 600519"
$code = $code.Trim()

if ($code -notmatch "^\d{6}$") {
    Write-Host "[X] Invalid stock code: $code" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$stockName = Read-Host "Stock name, optional, for example 贵州茅台"
$stockName = $stockName.Trim()

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "output") | Out-Null

Write-Host ""
Write-Host "[1/3] Collecting stock data for $code ..." -ForegroundColor Yellow
& $VenvPython stock_full_report.py $code

$dataPath = Join-Path $ProjectRoot "output\data_$code.json"
if (!(Test-Path $dataPath)) {
    Write-Host "[X] Data file was not created: $dataPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$summaryPath = Join-Path $ProjectRoot "output\summary_$code.html"
Write-Host ""
Write-Host "[View] Creating readable HTML data summary ..." -ForegroundColor Yellow
& $VenvPython view_stock_data.py $dataPath --output $summaryPath

if (Test-Path "Env:\DEEPSEEK_API_KEY") {
    Write-Host ""
    Write-Host "[2/3] Calling DeepSeek and generating full HTML report ..." -ForegroundColor Yellow
    $reportArgs = @("generate_stock_report.py", $dataPath, "--auto-deepseek")
    if ($stockName) {
        $reportArgs += @("--name", $stockName)
    }
    $reportPath = (& $VenvPython @reportArgs | Select-Object -Last 1)

    Write-Host ""
    Write-Host "[3/3] Full report saved:" -ForegroundColor Green
    Write-Host $reportPath
    Start-Process $reportPath
} else {
    Write-Host ""
    Write-Host "[!] DEEPSEEK_API_KEY is not configured." -ForegroundColor Yellow
    Write-Host "DeepSeek analysis was skipped, but a full HTML report shell will still be created."
    Write-Host "Set DEEPSEEK_API_KEY in PowerShell or create a local .env file."
    $reportArgs = @("generate_stock_report.py", $dataPath)
    if ($stockName) {
        $reportArgs += @("--name", $stockName)
    }
    $reportPath = (& $VenvPython @reportArgs | Select-Object -Last 1)

    Write-Host "Data file: $dataPath"
    Write-Host "Readable summary: $summaryPath"
    Write-Host "Full report shell: $reportPath"
    Start-Process $reportPath
}

Write-Host ""
Read-Host "Done. Press Enter to close"
