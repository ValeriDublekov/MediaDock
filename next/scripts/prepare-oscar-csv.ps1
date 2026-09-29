[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter()]
    [string]$OutputPath,

    [Parameter()]
    [switch]$Force,

    [Parameter()]
    [ValidateRange(0, 9999)]
    [int]$YearAfter = 1980
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
    throw "Input file not found: $InputPath"
}

$inputFullPath = [System.IO.Path]::GetFullPath($InputPath)
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $outputDirectory = Split-Path -Parent $inputFullPath
    $OutputPath = Join-Path $outputDirectory "oscar_films_after_${YearAfter}_compact.csv"
}

$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
if ($inputFullPath -eq $outputFullPath) {
    throw 'OutputPath must not point to the input file.'
}
if ((Test-Path -LiteralPath $outputFullPath) -and -not $Force) {
    throw "Output file already exists: $outputFullPath"
}

$columns = @(
    'Ceremony',
    'Year',
    'Class',
    'CanonicalCategory',
    'Category',
    'Film',
    'FilmId',
    'Name',
    'Nominees',
    'NomineeIds',
    'Detail',
    'Winner'
)
$targetCategories = @(
    'BEST PICTURE',
    'DIRECTING',
    'WRITING (Original Screenplay)',
    'WRITING (Adapted Screenplay)',
    'CINEMATOGRAPHY'
)

$rows = @(Import-Csv -LiteralPath $inputFullPath -Delimiter "`t" -Encoding UTF8)
if ($rows.Count -eq 0) {
    throw 'Input file contains no data rows.'
}

$headers = @($rows[0].PSObject.Properties.Name)
$missingColumns = @($columns | Where-Object { $_ -notin $headers })
if ($missingColumns.Count -gt 0) {
    throw "Input file is missing required columns: $($missingColumns -join ', ')"
}

$yearRows = @($rows | Where-Object {
    $_.Year -match '^\d{4}$' -and [int]$_.Year -gt $YearAfter
})
$categoryRows = @($yearRows | Where-Object { $_.CanonicalCategory -in $targetCategories })
$filmRows = @($categoryRows | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Film) })
$compactRows = @($filmRows | Select-Object -Property $columns)

$compactRows | Export-Csv -LiteralPath $outputFullPath -NoTypeInformation -Encoding UTF8

$exportedRows = @(Import-Csv -LiteralPath $outputFullPath -Encoding UTF8)
if ($exportedRows.Count -ne $compactRows.Count) {
    throw "Export row count mismatch: expected $($compactRows.Count), found $($exportedRows.Count)."
}

$exportedColumns = @($exportedRows[0].PSObject.Properties.Name)
if (($exportedColumns -join ',') -ne ($columns -join ',')) {
    throw 'Exported CSV columns do not match the requested compact schema.'
}

$invalidRows = @($exportedRows | Where-Object {
    $_.Year -notmatch '^\d{4}$' -or [int]$_.Year -le $YearAfter -or $_.CanonicalCategory -notin $targetCategories -or [string]::IsNullOrWhiteSpace($_.Film)
})
if ($invalidRows.Count -gt 0) {
    throw "Export contains $($invalidRows.Count) rows outside the requested filter."
}

$categories = @($exportedRows | Select-Object -ExpandProperty CanonicalCategory -Unique | Sort-Object)
Write-Output "Output: $outputFullPath"
Write-Output "Source rows: $($rows.Count)"
Write-Output "Rows with Year > ${YearAfter}: $($yearRows.Count)"
Write-Output "Rows in target categories: $($categoryRows.Count)"
Write-Output "Rows excluded because Film is blank: $($categoryRows.Count - $filmRows.Count)"
Write-Output "Exported nomination rows: $($exportedRows.Count)"
Write-Output "Retained categories ($($categories.Count)): $($categories -join ' | ')"