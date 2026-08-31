# Параметри
param(
    [string]$Config = "legacy/config.json",
    [string]$Mode = "rss",
    [switch]$DryRun,
    [switch]$ParseOnly,
    [string]$FeedFile,
    [int]$ForceDays = 0,
    [int]$AuditDays = 0,
    [string]$ProposalId,
    [switch]$RejectProposal,
    [switch]$FakeRepos,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Помощна информация
if ($Help) {
    Write-Host @"
=== Movie Scanner - Help ===

Usage: .\scripts\run_scanner.ps1 [OPTIONS]

Options:
  -Config PATH       Path to configuration JSON file (default: legacy/config.json)
    -Mode MODE         Scanner mode (rss, recheck-existing, reparse-unfound, all, apply-proposals)
  -DryRun            Run without writing to Firestore
  -ParseOnly         Download/parse RSS only, no external APIs (requires -Mode rss)
  -FeedFile PATH     Path to local feed file (requires -Mode rss -ParseOnly)
  -ForceDays N       Force scan N days back (0-30)
  -AuditDays N       Audit N days back (0-30)
    -ProposalId ID     Explicit ID of the single proposal to plan/apply
  -RejectProposal    Reject proposal instead of applying
  -FakeRepos         Use fake repositories (no Firebase)
  -Help              Show this help message

Examples:
  .\scripts\run_scanner.ps1 -Mode rss
  .\scripts\run_scanner.ps1 -Mode rss -ParseOnly -FeedFile backend\tests\fixtures\movies_feed.atom
  .\scripts\run_scanner.ps1 -Mode recheck-existing -DryRun
    .\scripts\run_scanner.ps1 -Mode apply-proposals -ProposalId prop-123 -DryRun

Notes:
    -Mode all never applies proposals; there is no bulk proposal application mode.
    Non-dry-run application also requires MEDIADOCK_ENABLE_PROPOSAL_APPLICATION=true.

"@ -ForegroundColor Cyan
    exit 0
}

Write-Host "=== Movie Scanner ===" -ForegroundColor Cyan
Write-Host "Note: Legacy movie_scanner.py execution is unsupported." -ForegroundColor Yellow

# Проверка за Python
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Error: Python not found!" -ForegroundColor Red
    exit 1
}

# Изграждане на аргументи
$argsList = @()
if ($Config) { $argsList += "--config"; $argsList += $Config }
if ($Mode) { $argsList += "--mode"; $argsList += $Mode }
if ($DryRun) { $argsList += "--dry-run" }
if ($ParseOnly) { $argsList += "--parse-only" }
if ($FeedFile) { $argsList += "--feed-file"; $argsList += $FeedFile }
if ($ForceDays) { $argsList += "--force-days"; $argsList += $ForceDays }
if ($AuditDays) { $argsList += "--audit-days"; $argsList += $AuditDays }
if ($ProposalId) { $argsList += "--proposal-id"; $argsList += $ProposalId }
if ($RejectProposal) { $argsList += "--reject-proposal" }
if ($FakeRepos) { $argsList += "--fake-repos" }

# Изпълнение на скрипта
try {
    Write-Host "Running scanner..." -ForegroundColor Green
    python -m movies_feed.cli @argsList
    
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 2) {
        Write-Host "❌ Scanner failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    } elseif ($LASTEXITCODE -eq 2) {
        Write-Host "⚠️  Scanner completed partially (exit code 2)" -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
    
    Write-Host "`n✅ Done!" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
