$ErrorActionPreference = 'Stop'

$sourcePath = 'C:\Users\hp\Downloads\261907 LLM Agent Calculation v1.0.xlsx'
$outputDir = 'C:\AINewsletter_v0.2\outputs\gemini_cost_model_20260721'
$outputPath = Join-Path $outputDir 'AI Newsletter Gemini Cost Calculation.xlsx'
$pdfPath = Join-Path $outputDir 'AI Newsletter Gemini Cost Calculation.pdf'

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Copy-Item -LiteralPath $sourcePath -Destination $outputPath -Force
Unblock-File -LiteralPath $outputPath

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.AskToUpdateLinks = $false

$navy = 0x6B3F16
$blue = 0xA97325
$lightBlue = 0xEEDCCB
$teal = 0x8B6B20
$lightTeal = 0xE9F0DC
$yellow = 0xD9F2FF
$lightGray = 0xF2F2F2
$white = 0xFFFFFF
$dark = 0x2D2D2D
$green = 0x4F6228
$red = 0x0000C0
$thinGray = 0xD9D9D9

function Set-Title($sheet, $rangeAddress, $text) {
    $range = $sheet.Range($rangeAddress)
    $range.Merge()
    $range.Value2 = $text
    $range.Interior.Color = $navy
    $range.Font.Color = $white
    $range.Font.Bold = $true
    $range.Font.Size = 18
    $range.HorizontalAlignment = -4108
    $range.VerticalAlignment = -4108
}

function Set-Section($sheet, $rangeAddress, $text) {
    $range = $sheet.Range($rangeAddress)
    $range.Merge()
    $range.Value2 = $text
    $range.Interior.Color = $blue
    $range.Font.Color = $white
    $range.Font.Bold = $true
    $range.Font.Size = 11
    $range.HorizontalAlignment = -4131
    $range.VerticalAlignment = -4108
}

function Set-Headers($range) {
    $range.Interior.Color = $lightBlue
    $range.Font.Color = $dark
    $range.Font.Bold = $true
    $range.HorizontalAlignment = -4108
    $range.VerticalAlignment = -4108
    $range.WrapText = $true
}

function Set-Borders($range) {
    foreach ($edge in 7,8,9,10,11,12) {
        try {
            $range.Borders.Item($edge).LineStyle = 1
            $range.Borders.Item($edge).Color = $thinGray
            $range.Borders.Item($edge).Weight = 2
        } catch {}
    }
}

function Set-Grid($range, [object[]]$values) {
    $rowCount = $range.Rows.Count
    $columnCount = $range.Columns.Count
    if ($values.Count -ne ($rowCount * $columnCount)) {
        throw "Value count $($values.Count) does not match $rowCount x $columnCount for $($range.Address())"
    }
    $index = 0
    for ($row = 1; $row -le $rowCount; $row++) {
        for ($column = 1; $column -le $columnCount; $column++) {
            $cell = $range.Cells.Item($row, $column)
            $value = $values[$index]
            if ($null -eq $value) {
                $cell.ClearContents() | Out-Null
            } elseif ($value -is [byte] -or $value -is [int16] -or $value -is [int32] -or $value -is [int64] -or $value -is [single] -or $value -is [double] -or $value -is [decimal]) {
                $cell.Value2 = [double]$value
            } else {
                $cell.Value2 = [string]$value
            }
            $index++
        }
    }
}

try {
    $workbook = $excel.Workbooks.Open($outputPath, 0, $false)
    $calc = $workbook.Worksheets.Item('Cost Calculator')
    $defs = $workbook.Worksheets.Item('Definitions')
    try { $workbook.Worksheets.Item('Run Evidence').Delete() } catch {}
    $evidence = $workbook.Worksheets.Add($defs)
    $evidence.Name = 'Run Evidence'

    foreach ($sheet in @($calc, $evidence, $defs)) {
        $sheet.Cells.Clear()
        $sheet.Cells.UnMerge() | Out-Null
        try {
            if ($sheet.ChartObjects().Count -gt 0) { $sheet.ChartObjects().Delete() }
        } catch {}
        $sheet.Cells.Font.Name = 'Aptos'
        $sheet.Cells.Font.Size = 10
        $sheet.Activate()
        $excel.ActiveWindow.DisplayGridlines = $false
    }

    # Cost Calculator
    Set-Title $calc 'B1:K2' 'AI Newsletter - Gemini Cost Calculation'
    $calc.Range('B3:K3').Merge()
    $calc.Range('B3').Value2 = 'Gemini only | Production: one admin weekly | Developer tests | Failed admin attempts'
    $calc.Range('B3').Font.Italic = $true
    $calc.Range('B3').Font.Color = $dark
    $calc.Range('B3').HorizontalAlignment = -4108

    Set-Section $calc 'B5:K5' '1. WEEKLY USAGE ASSUMPTIONS - EDIT YELLOW CELLS'
    $calc.Range('B6:H6').Value2 = @(
        @('Scenario / Actor','Runs per Week','Full-Run Equivalent','Equivalent Runs / Week','Equivalent Runs / Month','Equivalent Runs / Year','Notes')
    )
    Set-Headers $calc.Range('B6:H6')
    Set-Grid ($calc.Range('B7:B9')) @('Admin weekly generation','Developer testing','Admin failed attempts')
    Set-Grid ($calc.Range('C7:C9')) @(1,2,1)
    Set-Grid ($calc.Range('D7:D9')) @(1,0.25,0.5)
    $calc.Range('E7').Formula = '=C7*D7'
    $calc.Range('E7:E9').FillDown()
    $calc.Range('F7').Formula = '=E7*52/12'
    $calc.Range('F7:F9').FillDown()
    $calc.Range('G7').Formula = '=E7*52'
    $calc.Range('G7:G9').FillDown()
    Set-Grid ($calc.Range('H7:H9')) @(
        'One full Generate run each week by the admin',
        'Two focused tests; each assumed at 25% of a full run',
        'One failed/retried admin attempt; assumed to consume 50% of a full run'
    )
    $calc.Range('B10').Value2 = 'Total equivalent usage'
    $calc.Range('E10').Formula = '=SUM(E7:E9)'
    $calc.Range('F10').Formula = '=SUM(F7:F9)'
    $calc.Range('G10').Formula = '=SUM(G7:G9)'
    $calc.Range('B10:H10').Interior.Color = $lightTeal
    $calc.Range('B10:H10').Font.Bold = $true
    $calc.Range('C7:D9').Interior.Color = $yellow
    $calc.Range('C7:D9').Font.Color = $blue
    $calc.Range('D7:D9').NumberFormat = '0%'
    $calc.Range('E7:G10').NumberFormat = '0.00'
    Set-Borders $calc.Range('B6:H10')

    Set-Section $calc 'B12:K12' '2. GEMINI MODEL USAGE PER FULL SUCCESSFUL RUN'
    $calc.Range('B13:K13').Value2 = @(
        @('Role','Gemini Model','Calls / Run','Input Tokens / Run','Visible Output Tokens','Thinking Tokens','Billed Output Tokens','Input $ / 1M','Output $ / 1M','Cost / Full Run')
    )
    Set-Headers $calc.Range('B13:K13')
    Set-Grid ($calc.Range('B14:C16')) @(
        'Selection + supporting','gemini-flash-latest',
        'Arabic rewrite','gemini-3.1-pro-preview',
        'Semantic memory','gemini-embedding-001'
    )
    Set-Grid ($calc.Range('D14:J16')) @(
        6,58644,13008,52480,$null,0.5,3,
        3,10528,3061,27329,$null,2,12,
        7,25000,0,0,$null,0.15,0
    )
    $calc.Range('H14').Formula = '=F14+G14'
    $calc.Range('H14:H16').FillDown()
    $calc.Range('K14').Formula = '=E14/1000000*I14+H14/1000000*J14'
    $calc.Range('K14:K16').FillDown()
    $calc.Range('B17').Value2 = 'Total per full-equivalent run'
    $calc.Range('D17').Formula = '=SUM(D14:D16)'
    $calc.Range('E17').Formula = '=SUM(E14:E16)'
    $calc.Range('F17').Formula = '=SUM(F14:F16)'
    $calc.Range('G17').Formula = '=SUM(G14:G16)'
    $calc.Range('H17').Formula = '=SUM(H14:H16)'
    $calc.Range('K17').Formula = '=SUM(K14:K16)'
    $calc.Range('B17:K17').Interior.Color = $lightTeal
    $calc.Range('B17:K17').Font.Bold = $true
    $calc.Range('D14:J16').Interior.Color = $yellow
    $calc.Range('D14:J16').Font.Color = $blue
    $calc.Range('D14:H17').NumberFormat = '#,##0'
    $calc.Range('I14:K17').NumberFormat = '$0.0000'
    Set-Borders $calc.Range('B13:K17')

    $calc.Range('B19').Value2 = 'Usage buffer'
    $calc.Range('C19').Value2 = 0.2
    $calc.Range('C19').NumberFormat = '0%'
    $calc.Range('C19').Interior.Color = $yellow
    $calc.Range('C19').Font.Color = $blue
    $calc.Range('E19').Value2 = 'Daily request tracker'
    $calc.Range('F19').Value2 = 120
    $calc.Range('F19').Interior.Color = $yellow
    $calc.Range('H19:K20').Merge()
    $calc.Range('H19').Value2 = 'Paid Standard rates. Flash alias is costed as Gemini 3 Flash Preview; update the yellow price cells if the alias changes.'
    $calc.Range('H19').WrapText = $true
    $calc.Range('H19').Font.Italic = $true
    $calc.Range('H19').Font.Color = $dark

    Set-Section $calc 'B22:K22' '3. COST SUMMARY'
    $calc.Range('B23:C23').Value2 = @(@('Cost Metric','Calculated Cost'))
    Set-Headers $calc.Range('B23:C23')
    Set-Grid ($calc.Range('B24:B30')) @(
        'Cost per full-equivalent run',
        'Weekly cost incl. buffer',
        'Monthly recurring cost incl. buffer',
        'Annual recurring cost incl. buffer',
        'Admin weekly generation - annual',
        'Developer testing - annual',
        'Admin failed attempts - annual'
    )
    $calc.Range('C24').Formula = '=K17'
    $calc.Range('C25').Formula = '=K17*E10*(1+$C$19)'
    $calc.Range('C26').Formula = '=K17*F10*(1+$C$19)'
    $calc.Range('C27').Formula = '=K17*G10*(1+$C$19)'
    $calc.Range('C28').Formula = '=K17*G7*(1+$C$19)'
    $calc.Range('C29').Formula = '=K17*G8*(1+$C$19)'
    $calc.Range('C30').Formula = '=K17*G9*(1+$C$19)'
    $calc.Range('C24:C30').NumberFormat = '$0.00'
    $calc.Range('B27:C27').Interior.Color = $teal
    $calc.Range('B27:C27').Font.Color = $white
    $calc.Range('B27:C27').Font.Bold = $true
    Set-Borders $calc.Range('B23:C30')

    $calc.Range('E23:K23').Value2 = @(@('Scenario','Weekly Eq.','Monthly Eq.','Annual Eq.','Weekly Cost','Monthly Cost','Annual Cost'))
    Set-Headers $calc.Range('E23:K23')
    Set-Grid ($calc.Range('E24:E26')) @('Admin weekly generation','Developer testing','Admin failed attempts')
    $calc.Range('F24').Formula = '=E7'
    $calc.Range('F24:F26').FillDown()
    $calc.Range('G24').Formula = '=F7'
    $calc.Range('G24:G26').FillDown()
    $calc.Range('H24').Formula = '=G7'
    $calc.Range('H24:H26').FillDown()
    $calc.Range('I24').Formula = '=$K$17*F24*(1+$C$19)'
    $calc.Range('I24:I26').FillDown()
    $calc.Range('J24').Formula = '=$K$17*G24*(1+$C$19)'
    $calc.Range('J24:J26').FillDown()
    $calc.Range('K24').Formula = '=$K$17*H24*(1+$C$19)'
    $calc.Range('K24:K26').FillDown()
    $calc.Range('F24:H26').NumberFormat = '0.00'
    $calc.Range('I24:K26').NumberFormat = '$0.00'
    Set-Borders $calc.Range('E23:K26')

    $calc.Range('B33:D38').Merge()
    $calc.Range('B33').Value2 = 'Scope: Gemini API costs only. Excludes Exa, SearXNG hosting, Docker/servers, databases, storage, networking, and developer labor. End users reading the newsletter do not trigger Gemini; only admin generation, developer tests, and failed admin attempts are modeled.'
    $calc.Range('B33').WrapText = $true
    $calc.Range('B33').Interior.Color = $lightGray
    $calc.Range('B33').Font.Italic = $true
    $calc.Range('B33').VerticalAlignment = -4108

    Set-Grid ($calc.Range('M23:N26')) @(
        'Scenario','Annual Cost',
        'Admin weekly generation',$null,
        'Developer testing',$null,
        'Admin failed attempts',$null
    )
    $calc.Range('N24').Formula = '=K24'
    $calc.Range('N24:N26').FillDown()
    $chartObj = $calc.ChartObjects().Add($calc.Range('E28').Left, $calc.Range('E28').Top, 520, 230)
    $chart = $chartObj.Chart
    $chart.ChartType = 51
    $chart.SetSourceData($calc.Range('M23:N26'))
    $chart.PlotVisibleOnly = $false
    $chart.HasTitle = $true
    $chart.ChartTitle.Text = 'Annual Gemini Cost by Usage Scenario'
    $chart.HasLegend = $false
    $chart.Axes(2).TickLabels.NumberFormat = '0.00'
    $chart.Axes(2).HasTitle = $true
    $chart.Axes(2).AxisTitle.Text = 'USD'
    $calc.Columns.Item('M').Hidden = $true
    $calc.Columns.Item('N').Hidden = $true

    $calc.Columns.Item('A').ColumnWidth = 2
    $calc.Columns.Item('B').ColumnWidth = 28
    $calc.Columns.Item('C').ColumnWidth = 24
    $calc.Columns.Item('D').ColumnWidth = 18
    $calc.Columns.Item('E').ColumnWidth = 24
    $calc.Columns.Item('F').ColumnWidth = 17
    $calc.Columns.Item('G').ColumnWidth = 17
    $calc.Columns.Item('H').ColumnWidth = 30
    $calc.Columns.Item('I').ColumnWidth = 15
    $calc.Columns.Item('J').ColumnWidth = 15
    $calc.Columns.Item('K').ColumnWidth = 17
    $calc.Rows.Item(1).RowHeight = 28
    $calc.Rows.Item(2).RowHeight = 18
    $calc.Rows.Item(3).RowHeight = 24
    $calc.Rows.Item(6).RowHeight = 36
    $calc.Rows.Item(7).RowHeight = 38
    $calc.Rows.Item(8).RowHeight = 38
    $calc.Rows.Item(9).RowHeight = 44
    $calc.Rows.Item(13).RowHeight = 44
    $calc.Rows.Item(33).RowHeight = 28
    $calc.Range('B1:K35').VerticalAlignment = -4108
    $calc.Range('B1:K35').WrapText = $true
    $calc.Range('B7:B35').HorizontalAlignment = -4131
    $calc.Range('C7:K30').HorizontalAlignment = -4152
    $calc.PageSetup.Orientation = 2
    $calc.PageSetup.Zoom = $false
    $calc.PageSetup.FitToPagesWide = 1
    $calc.PageSetup.FitToPagesTall = 1
    $calc.PageSetup.PrintArea = '$B$1:$K$42'

    # Run Evidence
    Set-Title $evidence 'B1:I2' 'Measured Gemini Usage - Baseline Run'
    $evidence.Range('B3:I3').Merge()
    $evidence.Range('B3').Value2 = 'Source run: full-20260720T112453Z-fe7ccc2e | Successful full pipeline | 18 selected news items'
    $evidence.Range('B3').HorizontalAlignment = -4108
    Set-Section $evidence 'B5:I5' 'ACTUAL TOKEN USAGE FROM MODEL.TOKEN_USAGE EVENTS'
    $evidence.Range('B6:I6').Value2 = @(@('Model','Calls','Input Tokens','Visible Output','Thinking Tokens','Billed Output','Total Tokens','Notes'))
    Set-Headers $evidence.Range('B6:I6')
    Set-Grid ($evidence.Range('B7:I9')) @(
        'gemini-flash-latest',6,58644,13008,52480,65488,124132,'Selection, top-ups, courses and movies',
        'gemini-3.1-pro-preview',3,10528,3061,27329,30390,40918,'Arabic rewrite calls',
        'gemini-embedding-001',7,25000,0,0,0,25000,'Estimated token volume; 7 calls inferred from 16 total requests minus 9 generation calls'
    )
    $evidence.Range('B10').Value2 = 'Total'
    foreach ($col in 'C','D','E','F','G','H') { $evidence.Range("${col}10").Formula = "=SUM(${col}7:${col}9)" }
    $evidence.Range('B10:I10').Interior.Color = $lightTeal
    $evidence.Range('B10:I10').Font.Bold = $true
    $evidence.Range('C7:H10').NumberFormat = '#,##0'
    Set-Borders $evidence.Range('B6:I10')

    Set-Section $evidence 'B12:I12' 'STAGE DETAIL'
    $evidence.Range('B13:I13').Value2 = @(@('Stage','Model','Input','Visible Output','Thinking','Total','Candidates','Status'))
    Set-Headers $evidence.Range('B13:I13')
    Set-Grid ($evidence.Range('B14:I22')) @(
        'primary','gemini-flash-latest',21224,3509,17915,42648,52,'Success',
        'primary_rewrite','gemini-3.1-pro-preview',4349,1261,10855,16465,13,'Success',
        'topup_1','gemini-flash-latest',16949,3000,12472,32421,40,'Success',
        'topup_1_rewrite','gemini-3.1-pro-preview',4209,1611,8914,14734,12,'Success',
        'topup_2','gemini-flash-latest',8157,955,8294,17406,16,'Success',
        'topup_2_rewrite','gemini-3.1-pro-preview',1970,189,7560,9719,3,'Success',
        'supporting_movie','gemini-flash-latest',1236,943,1986,4165,5,'Success',
        'supporting_course','gemini-flash-latest',3519,1374,4591,9484,6,'Success',
        'supporting_course','gemini-flash-latest',7559,3227,7222,18008,16,'Success'
    )
    $evidence.Range('D14:H22').NumberFormat = '#,##0'
    Set-Borders $evidence.Range('B13:I22')
    $evidence.Range('B24:I27').Merge()
    $evidence.Range('B24').Value2 = 'Why thinking is included: Gemini prices model output including thinking tokens. The visible response alone materially understates cost in this workload. Embedding tokens are estimated because the SDK usage state records embedded item count rather than token count.'
    $evidence.Range('B24').WrapText = $true
    $evidence.Range('B24').Interior.Color = $lightGray
    $evidence.Columns.Item('A').ColumnWidth = 2
    $evidence.Columns.Item('B').ColumnWidth = 25
    $evidence.Columns.Item('C').ColumnWidth = 24
    foreach ($col in 'D','E','F','G','H') { $evidence.Columns.Item($col).ColumnWidth = 16 }
    $evidence.Columns.Item('I').ColumnWidth = 40
    $evidence.Rows.Item(6).RowHeight = 36
    $evidence.Rows.Item(13).RowHeight = 34
    $evidence.Rows.Item(24).RowHeight = 54
    $evidence.Range('B1:I27').WrapText = $true
    $evidence.PageSetup.Orientation = 2
    $evidence.PageSetup.Zoom = $false
    $evidence.PageSetup.FitToPagesWide = 1
    $evidence.PageSetup.FitToPagesTall = 1
    $evidence.PageSetup.PrintArea = '$B$1:$I$27'

    # Definitions and sources
    Set-Title $defs 'B1:E2' 'Definitions, Assumptions & Sources'
    Set-Section $defs 'B4:E4' 'MODEL SCOPE'
    $defs.Range('B5:E5').Value2 = @(@('Group','Attribute','Definition / Assumption','Source'))
    Set-Headers $defs.Range('B5:E5')
    Set-Grid ($defs.Range('B6:E18')) @(
        'Scope','Provider','Gemini only. OpenAI is excluded from every calculation.','Project configuration',
        'Usage','Admin weekly generation','One successful full Generate run per week by one admin.','User requirement',
        'Usage','Developer testing','Two tests per week, each modeled as 25% of a full run. Editable.','Planning assumption',
        'Usage','Admin failed attempts','One failed/retried attempt per week, modeled as 50% of a full run. Editable.','Planning assumption',
        'Usage','End users','Newsletter readers do not invoke Gemini and therefore add no model cost.','System authorization flow',
        'Pricing','Gemini Flash alias','Priced as Gemini 3 Flash Preview: $0.50 input and $3.00 output per 1M tokens.','https://ai.google.dev/gemini-api/docs/gemini-3',
        'Pricing','Gemini 3.1 Pro Preview','$2.00 input and $12.00 output per 1M tokens below 200k input tokens.','https://ai.google.dev/gemini-api/docs/gemini-3',
        'Pricing','Gemini Embedding 001','$0.15 per 1M input tokens under Standard paid pricing.','https://ai.google.dev/gemini-api/docs/pricing',
        'Tokens','Billed output','Visible output tokens plus thinking tokens.','https://ai.google.dev/gemini-api/docs/pricing',
        'Baseline','Measured run','Actual token usage from successful run full-20260720T112453Z-fe7ccc2e.','Local RUNLOG model.token_usage events',
        'Baseline','Embedding volume','25,000 tokens per full run estimated from semantic checks and saves; editable.','Project semantic memory flow',
        'Risk','Usage buffer','20% allowance for retries, variance and larger runs. Editable.','Planning assumption',
        'Exclusions','Non-Gemini costs','Exa, infrastructure, databases, storage, network and labor are excluded.','Workbook scope'
    )
    Set-Borders $defs.Range('B5:E18')
    $defs.Range('E6:E18').Font.Color = $green
    $defs.Columns.Item('A').ColumnWidth = 2
    $defs.Columns.Item('B').ColumnWidth = 18
    $defs.Columns.Item('C').ColumnWidth = 28
    $defs.Columns.Item('D').ColumnWidth = 65
    $defs.Columns.Item('E').ColumnWidth = 55
    $defs.Range('B1:E18').WrapText = $true
    $defs.Rows.Item(5).RowHeight = 30
    $defs.Range('B6:E18').Rows.AutoFit()
    $defs.PageSetup.Orientation = 2
    $defs.PageSetup.Zoom = $false
    $defs.PageSetup.FitToPagesWide = 1
    $defs.PageSetup.FitToPagesTall = 1
    $defs.PageSetup.PrintArea = '$B$1:$E$18'

    $calc.Activate()
    $excel.CalculateFull()
    $workbook.Save()
    $workbook.ExportAsFixedFormat(0, $pdfPath)
    $workbook.Close($true)
} finally {
    $excel.Quit()
    [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}

Write-Output "OUTPUT=$outputPath"
Write-Output "PDF=$pdfPath"
