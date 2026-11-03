# Uses Microsoft Word to fill in the contents pages and save ReadMe as a real .doc file.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $files = @(Get-ChildItem (Join-Path $root 'docs') -Filter 'EarthScape_*.docx') + (Get-Item (Join-Path $root 'ReadMe.docx'))
    foreach ($file in $files) {
        $doc = $word.Documents.Open($file.FullName, $false, $false, $false)
        if ($doc.TablesOfContents.Count -gt 0) { $doc.TablesOfContents.Item(1).Update() }
        Write-Output ("{0}: {1} pages" -f $file.BaseName, $doc.ComputeStatistics(2))
        if ($file.Name -eq 'ReadMe.docx') {
            $doc.SaveAs([ref](Join-Path $root 'ReadMe.doc'), [ref]0)
        } else {
            $doc.Save()
        }
        $doc.Close(0)
    }
} finally {
    $word.Quit()
}
Remove-Item (Join-Path $root 'ReadMe.docx')
