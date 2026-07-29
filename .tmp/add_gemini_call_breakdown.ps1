param(
    [string]$SourcePath = 'C:\Users\hp\Downloads\Gemini_Cost_Calculator.xlsx',
    [string]$ProjectOutput = 'C:\AINewsletter_v0.2\outputs\gemini_call_breakdown_20260722\Gemini_Cost_Calculator_Detailed.xlsx',
    [string]$DownloadOutput = 'C:\Users\hp\Downloads\Gemini_Cost_Calculator_Detailed.xlsx'
)

$ErrorActionPreference = 'Stop'

function ExcelRgb([int]$r, [int]$g, [int]$b) {
    return $r + (256 * $g) + (65536 * $b)
}

$outputDir = Split-Path -Parent $ProjectOutput
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Copy-Item -LiteralPath $SourcePath -Destination $ProjectOutput -Force

$excel = $null
$workbook = $null
$summary = $null
$sheet = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $workbook = $excel.Workbooks.Open($ProjectOutput)

    $summary = $workbook.Worksheets.Item('Cost Calculator')

    # Use the model and prices supplied by the user in the latest approved table.
    $summary.Range('C14').Value2 = 'gemini-3.5-flash'
    $summary.Range('I14').Value2 = 1.5
    $summary.Range('J14').Value2 = 9.0
    $summary.Range('H14').Formula = '=F14+G14'
    $summary.Range('K14').Formula = '=E14/1000000*I14+H14/1000000*J14'
    $summary.Range('K17').Formula = '=SUM(K14:K16)'
    $summary.Range('H19').Value2 = 'Rates supplied for the approved Gemini-only cost model. Runtime evidence used the gemini-flash-latest alias; this workbook costs those measured tokens as gemini-3.5-flash.'
    $summary.Range('B20:G20').ClearContents()
    $summary.Range('B20').Value2 = 'Detailed 16-call trace'
    $summary.Range('C20').Formula = '=HYPERLINK("#''Call Breakdown''!B1","Open call-by-call explanation")'
    $summary.Range('B20:G20').Interior.Color = ExcelRgb 221 235 247
    $summary.Range('B20').Font.Bold = $true
    $summary.Range('C20').Font.Color = ExcelRgb 5 99 193
    $summary.Range('C20').Font.Underline = $true

    foreach ($existing in @($workbook.Worksheets)) {
        if ($existing.Name -eq 'Call Breakdown') {
            $existing.Delete()
            break
        }
    }

    $missing = [Type]::Missing
    $sheet = $workbook.Worksheets.Add($missing, $summary, 1, $missing)
    $sheet.Name = 'Call Breakdown'
    $sheet.DisplayRightToLeft = $false

    $navy = ExcelRgb 31 78 121
    $blue = ExcelRgb 91 155 213
    $lightBlue = ExcelRgb 221 235 247
    $lighterBlue = ExcelRgb 242 247 252
    $yellow = ExcelRgb 255 242 204
    $green = ExcelRgb 226 239 218
    $lightGray = ExcelRgb 242 242 242
    $white = ExcelRgb 255 255 255
    $dark = ExcelRgb 31 31 31

    $sheet.Range('B1:P1').Merge()
    $sheet.Range('B1').Value2 = 'CALL-BY-CALL BREAKDOWN — WHY THE FULL RUN USES 16 GEMINI REQUESTS'
    $sheet.Range('B1:P1').Interior.Color = $navy
    $sheet.Range('B1:P1').Font.Color = $white
    $sheet.Range('B1:P1').Font.Bold = $true
    $sheet.Range('B1:P1').Font.Size = 16
    $sheet.Range('B1:P1').HorizontalAlignment = -4108
    $sheet.Range('B1:P1').RowHeight = 30

    $sheet.Range('B2:P2').Merge()
    $sheet.Range('B2').Value2 = 'كل صف أدناه هو طلب مستقل إلى Gemini في الرن الناجح. رقم الطلب يطابق ترتيب الحصة الفعلي من 1 إلى 16.'
    $sheet.Range('B2:P2').Interior.Color = $lightBlue
    $sheet.Range('B2:P2').Font.Bold = $true
    $sheet.Range('B2:P2').HorizontalAlignment = -4108
    $sheet.Range('B2:P2').RowHeight = 24

    $sheet.Range('B3:P3').Merge()
    $sheet.Range('B3').Value2 = 'مهم: توكنات التوليد مقاسة من model.token_usage. Gemini Embedding سجّل عدد النصوص فقط، لذلك وُزّعت فرضية 25,000 توكن نسبيًا حسب عدد النصوص؛ الإجمالي والتكلفة محفوظان كما في الملخص.'
    $sheet.Range('B3:P3').Interior.Color = $yellow
    $sheet.Range('B3:P3').WrapText = $true
    $sheet.Range('B3:P3').RowHeight = 36

    $headers = @(
        'Request # / رقم الطلب',
        'Role / الفئة',
        'Costed Gemini Model',
        'Stage / المرحلة',
        'Why this call? / لماذا؟',
        'Trigger / ما الذي شغّله؟',
        'Items / Texts',
        'Input Tokens',
        'Visible Output',
        'Thinking Tokens',
        'Billed Output',
        'Input $ / 1M',
        'Output $ / 1M',
        'Cost / Call',
        'Evidence / ملاحظة'
    )
    for ($i = 0; $i -lt $headers.Count; $i++) {
        $sheet.Cells.Item(5, 2 + $i).Value2 = $headers[$i]
    }
    $sheet.Range('B5:P5').Interior.Color = $navy
    $sheet.Range('B5:P5').Font.Color = $white
    $sheet.Range('B5:P5').Font.Bold = $true
    $sheet.Range('B5:P5').WrapText = $true
    $sheet.Range('B5:P5').HorizontalAlignment = -4108
    $sheet.Range('B5:P5').VerticalAlignment = -4108
    $sheet.Range('B5:P5').RowHeight = 34

    # request, role, model, stage, purpose, trigger, items, input, visible, thinking, evidence
    $rows = @(
        @(1,  'Semantic memory',       'gemini-embedding-001',     'news_semantic_filter',      'يفحص تشابه الأخبار مع ذاكرة Qdrant ويمنع تكرار قصة قديمة أو تكرارًا داخل الرن نفسه.',             'قبل أول اختيار للأخبار.',                                           32, $null, 0,    0,     '32 semantic decisions before primary.'),
        @(2,  'Selection + supporting','gemini-3.5-flash',         'primary',                   'الاختيار الأساسي: يقرأ المرشحين ويرتّبهم ويختار الدفعة الأولى من أخبار النشرة.',                    'بداية مرحلة اختيار الأخبار؛ ليس Retry.',                              52, 21224, 3509, 17915, 'Runtime alias: gemini-flash-latest.'),
        @(3,  'Arabic rewrite',        'gemini-3.1-pro-preview',   'primary_rewrite',           'يعيد كتابة الأخبار التي اختارها Flash بالعربية وبصيغة البطاقة النهائية.',                           'Flash اختار 13 خبرًا في الدفعة الأساسية.',                            13, 4349,  1261, 10855, 'Measured model.token_usage.'),
        @(4,  'Selection + supporting','gemini-3.5-flash',         'topup_1',                   'تعويض أول لأن الدفعة الأساسية وحدها لم تكمل العدد المطلوب بعد التحقق والاستبعاد.',                   'بقي نقص؛ أُرسلت مجموعة من المرشحين المتبقين.',                         40, 16949, 3000, 12472, 'Top-up is expected conditional pipeline work.'),
        @(5,  'Arabic rewrite',        'gemini-3.1-pro-preview',   'topup_1_rewrite',           'يعيد كتابة أخبار التعويض الأول بالعربية بعد اعتمادها.',                                                'Top-up 1 أعاد 12 خبرًا مقبولًا لإعادة الصياغة.',                       12, 4209,  1611, 8914,  'Measured model.token_usage.'),
        @(6,  'Selection + supporting','gemini-3.5-flash',         'topup_2',                   'تعويض ثانٍ لأن العدد ظل ناقصًا بعد التعويض الأول.',                                                    'بقي نقص آخر؛ أُرسلت آخر مجموعة مناسبة من المرشحين.',                   16, 8157,  955,  8294,  'Second conditional top-up.'),
        @(7,  'Arabic rewrite',        'gemini-3.1-pro-preview',   'topup_2_rewrite',           'يعيد كتابة أخبار التعويض الثاني بالعربية لإضافتها إلى الناتج النهائي.',                                'Top-up 2 أعاد 3 أخبار مقبولة.',                                        3, 1970,  189,  7560,  'Measured model.token_usage.'),
        @(8,  'Semantic memory',       'gemini-embedding-001',     'news_memory_save',          'يحوّل الأخبار النهائية إلى Embeddings ويحفظها حتى لا تتكرر في الأسابيع القادمة.',                    'بعد نجاح اختيار وإعادة كتابة 18 خبرًا.',                              18, $null, 0,    0,     'News save occurs after request 7 and before supporting selection.'),
        @(9,  'Semantic memory',       'gemini-embedding-001',     'movie_semantic_filter',     'يفحص الأفلام المرشحة ضد الذاكرة الدلالية قبل إرسالها إلى موديل الاختيار.',                             'بدء مسار الأفلام الداعمة.',                                           5,  $null, 0,    0,     '5 movie semantic decisions before request 10.'),
        @(10, 'Selection + supporting','gemini-3.5-flash',         'supporting_movie',          'يختار ويصيغ بطاقات الأفلام الداعمة من المرشحين المقبولين.',                                            'انتهى فلتر الأفلام وبقي 5 مرشحين.',                                   5, 1236,  943,  1986,  'Runtime alias: gemini-flash-latest.'),
        @(11, 'Semantic memory',       'gemini-embedding-001',     'course_semantic_filter',    'يفحص دفعة الكورسات الأولى ضد الذاكرة ويمنع تكرار كورس ظاهر أو قديم.',                                  'بدء مسار الكورسات الداعمة.',                                          6,  $null, 0,    0,     '6 course semantic decisions before request 12.'),
        @(12, 'Selection + supporting','gemini-3.5-flash',         'supporting_course',         'يحاول اختيار وصياغة بطاقات الكورسات من الدفعة الأولى.',                                               'انتهى فلتر الدفعة الأولى وبقي 6 مرشحين.',                              6, 3519,  1374, 4591,  'The result did not fill the required course display count.'),
        @(13, 'Semantic memory',       'gemini-embedding-001',     'course_quick_fetch_filter', 'يفحص مرشحي Quick Fetch للكورسات؛ هذا الفحص منفصل لأن النظام جلب دفعة إضافية.',                          'الاستدعاء 12 لم يكمل العدد المطلوب، فبدأ Quick Fetch.',               12, $null, 0,    0,     '12 bounded semantic checks in the combined quick-fetch pool.'),
        @(14, 'Selection + supporting','gemini-3.5-flash',         'supporting_course_quick',   'يختار كورسات إضافية من الدفعة الموسعة لإكمال بنك/عرض الكورسات.',                                      'Quick Fetch جهّز 16 مرشحًا للموديل.',                                 16, 7559,  3227, 7222,  'Second course call is a refill, not a duplicate of request 12.'),
        @(15, 'Semantic memory',       'gemini-embedding-001',     'course_memory_save',        'يحفظ الكورسات الظاهرة فقط في الذاكرة الدلالية حتى لا تعود في رن لاحق.',                                 'بعد اعتماد بطاقات الكورسات النهائية.',                                2,  $null, 0,    0,     'Code saves visible_course_cards only.'),
        @(16, 'Semantic memory',       'gemini-embedding-001',     'movie_memory_save',         'يحفظ الأفلام الظاهرة فقط في الذاكرة الدلالية حتى لا تتكرر مستقبلًا.',                                  'بعد اعتماد بطاقات الأفلام النهائية.',                                 2,  $null, 0,    0,     'Final quota request; code saves visible_movie_cards only.')
    )

    for ($index = 0; $index -lt $rows.Count; $index++) {
        $excelRow = 6 + $index
        $item = $rows[$index]
        $sheet.Cells.Item($excelRow, 2).Value2 = [double]$item[0]
        $sheet.Cells.Item($excelRow, 3).Value2 = $item[1]
        $sheet.Cells.Item($excelRow, 4).Value2 = $item[2]
        $sheet.Cells.Item($excelRow, 5).Value2 = $item[3]
        $sheet.Cells.Item($excelRow, 6).Value2 = $item[4]
        $sheet.Cells.Item($excelRow, 7).Value2 = $item[5]
        $sheet.Cells.Item($excelRow, 8).Value2 = [double]$item[6]
        if ($null -ne $item[7]) {
            $sheet.Cells.Item($excelRow, 9).Value2 = [double]$item[7]
        } elseif ($item[0] -eq 16) {
            $sheet.Cells.Item($excelRow, 9).Formula = "='Cost Calculator'!`$E`$16-SUMIF(`$C`$6:`$C`$20,`"Semantic memory`",`$I`$6:`$I`$20)"
        } else {
            $sheet.Cells.Item($excelRow, 9).Formula = ('=ROUND(H{0}/SUMIF($C$6:$C$21,"Semantic memory",$H$6:$H$21)*''Cost Calculator''!$E$16,0)' -f $excelRow)
        }
        $sheet.Cells.Item($excelRow, 10).Value2 = [double]$item[8]
        $sheet.Cells.Item($excelRow, 11).Value2 = [double]$item[9]
        $sheet.Cells.Item($excelRow, 12).Formula = "=J$excelRow+K$excelRow"
        if ($item[1] -eq 'Selection + supporting') {
            $sheet.Cells.Item($excelRow, 13).Formula = "='Cost Calculator'!`$I`$14"
            $sheet.Cells.Item($excelRow, 14).Formula = "='Cost Calculator'!`$J`$14"
        } elseif ($item[1] -eq 'Arabic rewrite') {
            $sheet.Cells.Item($excelRow, 13).Formula = "='Cost Calculator'!`$I`$15"
            $sheet.Cells.Item($excelRow, 14).Formula = "='Cost Calculator'!`$J`$15"
        } else {
            $sheet.Cells.Item($excelRow, 13).Formula = "='Cost Calculator'!`$I`$16"
            $sheet.Cells.Item($excelRow, 14).Formula = "='Cost Calculator'!`$J`$16"
        }
        $sheet.Cells.Item($excelRow, 15).Formula = "=I$excelRow/1000000*M$excelRow+L$excelRow/1000000*N$excelRow"
        $sheet.Cells.Item($excelRow, 16).Value2 = $item[10]
        if (($excelRow % 2) -eq 0) {
            $sheet.Range("B${excelRow}:P${excelRow}").Interior.Color = $lighterBlue
        }
    }

    $sheet.Range('B22').Value2 = 'TOTAL'
    $sheet.Range('C22').Value2 = '16 requests'
    $sheet.Range('H22').Formula = '=SUM(H6:H21)'
    $sheet.Range('I22').Formula = '=SUM(I6:I21)'
    $sheet.Range('J22').Formula = '=SUM(J6:J21)'
    $sheet.Range('K22').Formula = '=SUM(K6:K21)'
    $sheet.Range('L22').Formula = '=SUM(L6:L21)'
    $sheet.Range('O22').Formula = '=SUM(O6:O21)'
    $sheet.Range('B22:P22').Interior.Color = $navy
    $sheet.Range('B22:P22').Font.Color = $white
    $sheet.Range('B22:P22').Font.Bold = $true

    $sheet.Range('B24:P24').Merge()
    $sheet.Range('B24').Value2 = 'WHY THE COUNTS ARE 6 + 3 + 7 / لماذا الأعداد 6 + 3 + 7؟'
    $sheet.Range('B24:P24').Interior.Color = $blue
    $sheet.Range('B24:P24').Font.Color = $white
    $sheet.Range('B24:P24').Font.Bold = $true

    $summaryHeaders = @('Role / الفئة','Calls','Exact breakdown / التفصيل','Why repeated / سبب التكرار','Cost / Full Run')
    $summaryCols = @(2,3,4,9,15)
    for ($i=0; $i -lt $summaryHeaders.Count; $i++) {
        $sheet.Cells.Item(25,$summaryCols[$i]).Value2 = $summaryHeaders[$i]
    }
    $sheet.Range('B25:O25').Interior.Color = $navy
    $sheet.Range('B25:O25').Font.Color = $white
    $sheet.Range('B25:O25').Font.Bold = $true

    $sheet.Range('B26').Value2 = 'Selection + supporting'
    $sheet.Range('C26').Formula = '=COUNTIF($C$6:$C$21,B26)'
    $sheet.Range('D26:H26').Merge()
    $sheet.Range('D26').Value2 = 'primary + topup_1 + topup_2 + movie + course + course quick fetch'
    $sheet.Range('I26:N26').Merge()
    $sheet.Range('I26').Value2 = '3 لاختيار الأخبار، 1 للأفلام، و2 للكورسات لأن الدفعة الأولى لم تكمل العدد.'
    $sheet.Range('O26').Formula = '=SUMIF($C$6:$C$21,B26,$O$6:$O$21)'

    $sheet.Range('B27').Value2 = 'Arabic rewrite'
    $sheet.Range('C27').Formula = '=COUNTIF($C$6:$C$21,B27)'
    $sheet.Range('D27:H27').Merge()
    $sheet.Range('D27').Value2 = 'primary_rewrite + topup_1_rewrite + topup_2_rewrite'
    $sheet.Range('I27:N27').Merge()
    $sheet.Range('I27').Value2 = 'كل دفعة أخبار مختارة تحتاج إعادة صياغة عربية مستقلة؛ لذلك تقابل 3 دفعات اختيار.'
    $sheet.Range('O27').Formula = '=SUMIF($C$6:$C$21,B27,$O$6:$O$21)'

    $sheet.Range('B28').Value2 = 'Semantic memory'
    $sheet.Range('C28').Formula = '=COUNTIF($C$6:$C$21,B28)'
    $sheet.Range('D28:H28').Merge()
    $sheet.Range('D28').Value2 = 'news check + news save + movie check + course check + course quick check + course save + movie save'
    $sheet.Range('I28:N28').Merge()
    $sheet.Range('I28').Value2 = 'فحص قبل الاختيار وحفظ بعد الاعتماد لكل نوع محتوى، مع فحص إضافي لدفعة Quick Fetch.'
    $sheet.Range('O28').Formula = '=SUMIF($C$6:$C$21,B28,$O$6:$O$21)'

    $sheet.Range('B29').Value2 = 'TOTAL'
    $sheet.Range('C29').Formula = '=SUM(C26:C28)'
    $sheet.Range('D29:N29').Merge()
    $sheet.Range('D29').Value2 = '6 + 3 + 7 = 16 independent Gemini requests in the measured successful run.'
    $sheet.Range('O29').Formula = '=SUM(O26:O28)'
    $sheet.Range('B29:O29').Interior.Color = $green
    $sheet.Range('B29:O29').Font.Bold = $true

    $sheet.Range('B5:P22').Borders.LineStyle = 1
    $sheet.Range('B25:O29').Borders.LineStyle = 1
    $sheet.Range('B6:P21').WrapText = $true
    $sheet.Range('B6:P21').VerticalAlignment = -4160
    $sheet.Range('B26:O29').WrapText = $true
    $sheet.Range('B26:O29').VerticalAlignment = -4160
    $sheet.Range('B6:B22').HorizontalAlignment = -4108
    $sheet.Range('H6:O22').HorizontalAlignment = -4152

    $sheet.Range('H6:L22').NumberFormat = '#,##0'
    $sheet.Range('M6:N21').NumberFormat = '$0.0000'
    $sheet.Range('O6:O29').NumberFormat = '$0.0000'

    $sheet.Columns.Item('A').ColumnWidth = 2
    $sheet.Columns.Item('B').ColumnWidth = 12
    $sheet.Columns.Item('C').ColumnWidth = 22
    $sheet.Columns.Item('D').ColumnWidth = 25
    $sheet.Columns.Item('E').ColumnWidth = 25
    $sheet.Columns.Item('F').ColumnWidth = 48
    $sheet.Columns.Item('G').ColumnWidth = 38
    $sheet.Columns.Item('H').ColumnWidth = 13
    $sheet.Columns.Item('I').ColumnWidth = 14
    $sheet.Columns.Item('J').ColumnWidth = 14
    $sheet.Columns.Item('K').ColumnWidth = 15
    $sheet.Columns.Item('L').ColumnWidth = 15
    $sheet.Columns.Item('M').ColumnWidth = 13
    $sheet.Columns.Item('N').ColumnWidth = 13
    $sheet.Columns.Item('O').ColumnWidth = 14
    $sheet.Columns.Item('P').ColumnWidth = 38
    $sheet.Rows.Item('6:21').RowHeight = 52
    $sheet.Rows.Item('26:28').RowHeight = 45
    $sheet.Rows.Item('29').RowHeight = 32

    $sheet.Range('B5:P21').AutoFilter() | Out-Null
    $sheet.Activate()
    $excel.ActiveWindow.SplitRow = 5
    $excel.ActiveWindow.FreezePanes = $true
    $excel.ActiveWindow.Zoom = 75

    $excel.CalculateFullRebuild()
    $workbook.Save()
    $workbook.Close($true)
    $workbook = $null
    $excel.Quit()
    $excel = $null

    Copy-Item -LiteralPath $ProjectOutput -Destination $DownloadOutput -Force
    Write-Output $ProjectOutput
    Write-Output $DownloadOutput
}
finally {
    if ($workbook -ne $null) { try { $workbook.Close($false) } catch {} }
    if ($excel -ne $null) { try { $excel.Quit() } catch {} }
    if ($sheet -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet) }
    if ($summary -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($summary) }
    if ($workbook -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) }
    if ($excel -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
