$ErrorActionPreference = 'Stop'
$inputPath = 'C:\AINewsletter_v0.2\outputs\gemini_cost_model_20260721\AI Newsletter Gemini Cost Calculation.xlsx'
$outputDir = 'C:\AINewsletter_v0.2\outputs\gemini_cost_model_20260721\previews'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $workbook = $excel.Workbooks.Open($inputPath, 0, $true)
    foreach ($sheet in $workbook.Worksheets) {
        $sheet.Activate()
        $used = $sheet.UsedRange
        $used.Select() | Out-Null
        $used.CopyPicture(1, 2)
        $width = [math]::Min(1800, [math]::Max(800, [double]$used.Width))
        $height = [math]::Min(2200, [math]::Max(500, [double]$used.Height))
        $previewChartObject = $sheet.ChartObjects().Add(0, 0, $width, $height)
        $previewChartObject.Activate()
        $previewChartObject.Chart.Paste() | Out-Null
        Start-Sleep -Milliseconds 500
        $safeName = $sheet.Name.Replace(' ', '_')
        $previewPath = Join-Path $outputDir "$safeName.png"
        $previewChartObject.Chart.Export($previewPath, 'PNG') | Out-Null
        $previewChartObject.Delete()
        Write-Output "PREVIEW=$previewPath"
        if ($sheet.ChartObjects().Count -gt 0) {
            $chartPath = Join-Path $outputDir "${safeName}_chart.png"
            $sheet.ChartObjects().Item(1).Activate()
            Start-Sleep -Milliseconds 300
            $sheet.ChartObjects().Item(1).Chart.Export($chartPath, 'PNG') | Out-Null
            Write-Output "CHART=$chartPath"
        }
    }
    $workbook.Close($false)
} finally {
    $excel.Quit()
    [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
