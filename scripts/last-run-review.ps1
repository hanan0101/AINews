param(
  [string]$OutFile = "last-run-review.txt",
  [int]$TopQueryResults = 5
)

$ErrorActionPreference = "Stop"

function Add-Line {
  param([System.Collections.Generic.List[string]]$Lines, [string]$Text = "")
  $Lines.Add($Text) | Out-Null
}

function PropMapLines {
  param($Object)
  if ($null -eq $Object) { return @() }
  return @($Object.PSObject.Properties | ForEach-Object { "  $($_.Name): $($_.Value)" })
}

function CountBy {
  param($Rows, [string]$Property)
  @($Rows | Group-Object $Property | Sort-Object Count -Descending | ForEach-Object {
    "  $($_.Name): $($_.Count)"
  })
}

function Trunc {
  param([string]$Text, [int]$Max = 180)
  $clean = (($Text -replace "\s+", " ").Trim())
  if ($clean.Length -le $Max) { return $clean }
  return $clean.Substring(0, $Max - 3) + "..."
}

$reportPath = "frontend\ai_updates_run_report.json"
$queryPath = "frontend\ai_updates_query_results.json"
$auditPath = "frontend\ai_updates_candidate_audit.json"

if (!(Test-Path $reportPath)) { throw "Missing $reportPath" }
if (!(Test-Path $queryPath)) { throw "Missing $queryPath" }
if (!(Test-Path $auditPath)) { throw "Missing $auditPath" }

$report = Get-Content $reportPath -Raw | ConvertFrom-Json
$queryAudit = Get-Content $queryPath -Raw | ConvertFrom-Json
$candidateAudit = Get-Content $auditPath -Raw | ConvertFrom-Json
$d = $report.diagnostics
$p = $report.performance
$lines = [System.Collections.Generic.List[string]]::new()

Add-Line $lines "=== Last AI Updates Run Review ==="
Add-Line $lines "Generated: $(Get-Date -Format s)"
Add-Line $lines "Report timestamp: $($report.timestamp)"
Add-Line $lines "Query audit timestamp: $($queryAudit.timestamp)"
Add-Line $lines "Candidate audit timestamp: $($candidateAudit.timestamp)"
Add-Line $lines ""

Add-Line $lines "=== Run Summary ==="
Add-Line $lines "success: $($report.success)"
Add-Line $lines "news_json_saved: $($p.news_json_saved)"
Add-Line $lines "selected_count: $($p.selected_count)"
Add-Line $lines "saved_count: $($p.saved_count)"
Add-Line $lines "total_seconds: $($p.total_seconds)"
Add-Line $lines "lookback_days: $($d.lookback_days)"
Add-Line $lines "cutoff_date: $($d.cutoff_date)"
Add-Line $lines ""

Add-Line $lines "=== Source Totals ==="
Add-Line $lines "total_queries: $($queryAudit.total_queries)"
Add-Line $lines "raw_results: $($queryAudit.raw_results)"
Add-Line $lines "unique_results: $($queryAudit.unique_results)"
Add-Line $lines "exa_queries: $($d.exa_queries)"
Add-Line $lines "exa_raw: $($d.exa_raw)"
Add-Line $lines "exa_seconds: $($d.exa_seconds)"
Add-Line $lines "searxng_queries: $($d.searxng_queries)"
Add-Line $lines "searxng_raw: $($d.searxng_raw)"
Add-Line $lines "searxng_seconds: $($d.searxng_seconds)"
Add-Line $lines "source_failures:"
PropMapLines $d.source_failures | ForEach-Object { Add-Line $lines $_ }
Add-Line $lines ""

Add-Line $lines "=== Query Mix ==="
Add-Line $lines "source candidate counts:"
PropMapLines $d.source_candidate_counts | ForEach-Object { Add-Line $lines $_ }
Add-Line $lines "query mix counts:"
if ($d.query_mix_counts) {
  foreach ($source in $d.query_mix_counts.PSObject.Properties) {
    Add-Line $lines "  [$($source.Name)]"
    PropMapLines $source.Value | ForEach-Object { Add-Line $lines "    $($_.Trim())" }
  }
}
Add-Line $lines ""

Add-Line $lines "=== Quality Filter ==="
Add-Line $lines "valid_before_memory: $($d.valid_before_memory)"
Add-Line $lines "unique_after_fetch: $($d.unique_results)"
Add-Line $lines "memory_exact_entries: $($d.memory_exact_entries)"
Add-Line $lines "memory_exact_skipped: $($d.memory_exact_skipped)"
Add-Line $lines "semantic_memory_checked: $($d.semantic_memory_checked)"
Add-Line $lines "semantic_memory_skipped: $($d.semantic_memory_skipped)"
Add-Line $lines "same_run_duplicates_skipped: $($d.same_run_duplicates_skipped)"
Add-Line $lines "same_run_story_duplicates_skipped: $($d.same_run_story_duplicates_skipped)"
Add-Line $lines "scan_pool_count: $($d.large_scan.scan_pool_count)"
Add-Line $lines "gpt_shortlist_count: $($d.large_scan.gpt_shortlist_count)"
Add-Line $lines ""

Add-Line $lines "=== Model Selection ==="
Add-Line $lines "payload_candidates: $($candidateAudit.total_candidates_sent_to_model)"
Add-Line $lines "selected_count: $($candidateAudit.selected_count)"
Add-Line $lines "rejected_count: $($candidateAudit.rejected_count)"
Add-Line $lines "gpt_primary_payload_candidates: $($d.gpt_primary_payload_candidates)"
Add-Line $lines "gpt_topup_attempted: $($d.gpt_topup_attempted)"
Add-Line $lines "gpt_topup_1_raw_selected: $($d.gpt_topup_1_raw_selected)"
Add-Line $lines "gpt_topup_2_raw_selected: $($d.gpt_topup_2_raw_selected)"
Add-Line $lines "company counts after balance:"
PropMapLines $d.company_counts_after_balance | ForEach-Object { Add-Line $lines $_ }
Add-Line $lines "sector counts after balance:"
PropMapLines $d.sector_counts_after_balance | ForEach-Object { Add-Line $lines $_ }
Add-Line $lines ""

Add-Line $lines "=== Model Decisions By Reason ==="
($candidateAudit.candidates | Group-Object status,reason | Sort-Object Count -Descending) | ForEach-Object {
  Add-Line $lines "  $($_.Count) - $($_.Name)"
}
Add-Line $lines ""

Add-Line $lines "=== Selected By Model ==="
$candidateAudit.candidates | Where-Object { $_.status -eq "selected" } | ForEach-Object {
  Add-Line $lines "[$($_.rank)] $($_.company) / $($_.tool)"
  Add-Line $lines "  title: $(Trunc $_.title 220)"
  Add-Line $lines "  source: $($_.fetch_source) | domain: $($_.source_domain) | sector: $($_.sector)"
  Add-Line $lines "  update_priority: $($_.update_priority) | signal: $($_.product_update_signal)"
  Add-Line $lines "  query: $(Trunc $_.query 220)"
  Add-Line $lines "  url: $($_.url)"
}
Add-Line $lines ""

Add-Line $lines "=== Rejected By Model ==="
$candidateAudit.candidates | Where-Object { $_.status -ne "selected" } | ForEach-Object {
  Add-Line $lines "[$($_.rank)] $($_.reason) | $($_.company) / $($_.tool)"
  Add-Line $lines "  title: $(Trunc $_.title 220)"
  Add-Line $lines "  source: $($_.fetch_source) | domain: $($_.source_domain) | query_mix: $($_.query_mix)"
  Add-Line $lines "  update_priority: $($_.update_priority) | signal: $($_.product_update_signal)"
}
Add-Line $lines ""

Add-Line $lines "=== Per Query Results ==="
$queryAudit.queries | Sort-Object source, query_mix, @{Expression="raw_count";Descending=$true} | ForEach-Object {
  Add-Line $lines "[$($_.source)] raw=$($_.raw_count) accepted=$($_.accepted_count) rejected=$($_.rejected_count) mix=$($_.query_mix) bucket=$($_.bucket)"
  Add-Line $lines "  tool: $($_.tool) | company: $($_.company) | official_site: $($_.official_site) | missing: $($_.official_site_missing)"
  Add-Line $lines "  query: $(Trunc $_.query 260)"
  if ($_.error) { Add-Line $lines "  error: $(Trunc $_.error 260)" }
  $results = @($_.results | Select-Object -First $TopQueryResults)
  foreach ($result in $results) {
    Add-Line $lines "    - $(Trunc $result.title 180)"
    Add-Line $lines "      url: $($result.url)"
  }
}

$text = $lines -join [Environment]::NewLine
Set-Content -Path $OutFile -Value $text -Encoding UTF8
Write-Host "Wrote $OutFile"
