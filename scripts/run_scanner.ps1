# Параметри
param(
    [switch]$HtmlOnly,
    [switch]$TestParser,
    [switch]$ParseOnly,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Помощна информация
if ($Help) {
    Write-Host @"
=== Movie Scanner - Help ===

Usage: .\scripts\run_scanner.ps1 [OPTIONS]

Options:
  -HtmlOnly       Regenerate HTML report without scanning RSS feeds
  -TestParser     Test the title parser without API calls
  -ParseOnly      Download/parse RSS only and print parsed titles/years
  -Help           Show this help message

Examples:
  .\scripts\run_scanner.ps1                # Full scan
  .\scripts\run_scanner.ps1 -HtmlOnly      # Only regenerate report
  .\scripts\run_scanner.ps1 -TestParser    # Test parser
  .\scripts\run_scanner.ps1 -ParseOnly     # Parse RSS without OMDb

"@ -ForegroundColor Cyan
    exit 0
}

Write-Host "=== Movie Scanner ===" -ForegroundColor Cyan

# Проверка за Python
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: Python not found!" -ForegroundColor Red
    exit 1
}

# Изграждане на аргументи
$args = @()
if ($HtmlOnly) { 
    $args += "--html"
    Write-Host "Mode: HTML regeneration only" -ForegroundColor Yellow
}
if ($TestParser) { 
    $args += "--test-parser"
    Write-Host "Mode: Parser test" -ForegroundColor Yellow
}
if ($ParseOnly) {
    $args += "--parse-only"
    Write-Host "Mode: Parse only" -ForegroundColor Yellow
}

# Изпълнение на скрипта
try {
    Write-Host "Running scanner..." -ForegroundColor Green
    python movie_scanner.py @args
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Scanner failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    
    # Отваряне на отчета (само ако не е test mode)
    if (!$TestParser -and !$ParseOnly) {
        $reportPath = "output\daily_report.html"
        if (Test-Path $reportPath) {
            Write-Host "✅ Opening report..." -ForegroundColor Green
            Start-Process $reportPath
        } else {
            Write-Host "⚠️  Warning: Report file not generated at $reportPath" -ForegroundColor Yellow
        }
    }
    
    Write-Host "`n✅ Done!" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
