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

$defaultPrompt = "Please produce a Step 0-8 stock analysis outline in Chinese, including key risks and follow-up indicators. This is research only and not investment advice."
$prompt = Read-Host "DeepSeek prompt, press Enter to use default"
if (!$prompt.Trim()) {
    $prompt = $defaultPrompt
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "output") | Out-Null

Write-Host ""
Write-Host "[1/2] Collecting stock data for $code ..." -ForegroundColor Yellow
& $VenvPython stock_full_report.py $code

$dataPath = Join-Path $ProjectRoot "output\data_$code.json"
if (!(Test-Path $dataPath)) {
    Write-Host "[X] Data file was not created: $dataPath" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

if (Test-Path "Env:\DEEPSEEK_API_KEY") {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmm"
    $analysisPath = Join-Path $ProjectRoot "output\deepseek_${code}_${timestamp}.md"

    Write-Host ""
    Write-Host "[2/2] Calling DeepSeek ..." -ForegroundColor Yellow
    & $VenvPython deepseek_client.py $prompt --stock-data $dataPath --output $analysisPath

    Write-Host ""
    Write-Host "[OK] Analysis saved:" -ForegroundColor Green
    Write-Host $analysisPath
    Start-Process notepad.exe $analysisPath
} else {
    Write-Host ""
    Write-Host "[!] DEEPSEEK_API_KEY is not configured." -ForegroundColor Yellow
    Write-Host "Data collection completed, but DeepSeek analysis was skipped."
    Write-Host "Set DEEPSEEK_API_KEY in PowerShell or create a local .env file."
    Write-Host "Data file: $dataPath"
}

Write-Host ""
Read-Host "Done. Press Enter to close"
