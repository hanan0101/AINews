param(
    [string]$InputPath = 'C:\Users\hp\Downloads\261907 LLM Agent Calculation v1.0.xlsx'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($InputPath)
try {
    function Read-ZipXml([string]$entryName) {
        $entry = $archive.GetEntry($entryName)
        if (-not $entry) { return $null }
        $reader = New-Object IO.StreamReader($entry.Open())
        try { return [xml]$reader.ReadToEnd() } finally { $reader.Dispose() }
    }

    $shared = @()
    $sharedXml = Read-ZipXml 'xl/sharedStrings.xml'
    if ($sharedXml) {
        foreach ($si in $sharedXml.sst.si) {
            $textParts = @($si.SelectNodes('.//*[local-name()="t"]') | ForEach-Object { $_.'#text' })
            $shared += ($textParts -join '')
        }
    }

    $workbookXml = Read-ZipXml 'xl/workbook.xml'
    $relsXml = Read-ZipXml 'xl/_rels/workbook.xml.rels'
    $relationships = @{}
    foreach ($rel in $relsXml.Relationships.Relationship) { $relationships[[string]$rel.Id] = [string]$rel.Target }

    foreach ($sheet in $workbookXml.workbook.sheets.sheet) {
        $relId = [string]$sheet.GetAttribute('id', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
        $target = $relationships[$relId].Replace('\', '/')
        if ($target.StartsWith('/')) { $entryName = $target.TrimStart('/') }
        elseif ($target.StartsWith('xl/')) { $entryName = $target }
        else { $entryName = "xl/$target" }
        $sheetXml = Read-ZipXml $entryName
        $dimension = $sheetXml.worksheet.dimension.ref
        Write-Output "SHEET=$($sheet.name) DIMENSION=$dimension ENTRY=$entryName"
        foreach ($row in $sheetXml.worksheet.sheetData.row) {
            $cells = @()
            foreach ($cell in $row.c) {
                $address = [string]$cell.r
                $formula = if ($cell.f) { "=$($cell.f)" } else { '' }
                $type = [string]$cell.t
                if ($type -eq 's') { $value = $shared[[int]$cell.v] }
                elseif ($type -eq 'inlineStr') { $value = (@($cell.is.SelectNodes('.//*[local-name()="t"]') | ForEach-Object { $_.'#text' }) -join '') }
                else { $value = [string]$cell.v }
                if ($value -or $formula) { $cells += "${address}:$value|FORMULA=$formula|STYLE=$($cell.s)" }
            }
            if ($cells.Count) { Write-Output ($cells -join "`t") }
        }
        $merges = @($sheetXml.worksheet.mergeCells.mergeCell | ForEach-Object { $_.ref })
        Write-Output "MERGES=$($merges -join ',')"
    }
} finally {
    $archive.Dispose()
}
