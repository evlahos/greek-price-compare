# -*- coding: utf-8 -*-
# Εγκατάσταση & εκκίνηση (καλείται από το INSTALL.bat μέσω PowerShell).
param([switch]$Browser)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   ΣΥΓΚΡΙΣΗ ΤΙΜΩΝ — Εγκατάσταση με ένα κλικ" -ForegroundColor Cyan
Write-Host "   Η πρώτη φορά αργεί (κατεβάζει τα απαραίτητα)." -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $p = & py -3 -c "import sys;print(sys.executable)" 2>$null
              if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() } } catch {}
    }
    $x = Get-Command python -ErrorAction SilentlyContinue
    if ($x -and $x.Source -notlike "*WindowsApps*") { return $x.Source }
    $c = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
         Sort-Object FullName -Descending | Select-Object -First 1
    if ($c) { return $c.FullName }
    return $null
}

# 1) Python
$py = Find-Python
if (-not $py) {
    Write-Host "[1/4] Εγκατάσταση Python..." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "[!] Χωρίς winget. Εγκατέστησε Python 3.10+ από https://www.python.org/downloads/ (Add to PATH) και ξανατρέξε." -ForegroundColor Red
        Read-Host "Enter"; exit 1
    }
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements | Out-Null
    $py = Find-Python
    if (-not $py) { Write-Host "[i] Η Python μπήκε. Κλείσε και ξανατρέξε το INSTALL.bat." -ForegroundColor Yellow; Read-Host "Enter"; exit 0 }
}
Write-Host "[1/4] Python: εντάξει" -ForegroundColor Green

# 2) venv
$venvPy  = Join-Path $here ".venv\Scripts\python.exe"
$venvPyw = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[2/4] Δημιουργία περιβάλλοντος..." -ForegroundColor Yellow
    & $py -m venv .venv
    if (-not (Test-Path $venvPy)) { Write-Host "[!] Αποτυχία .venv" -ForegroundColor Red; Read-Host "Enter"; exit 1 }
} else { Write-Host "[2/4] Περιβάλλον: εντάξει" -ForegroundColor Green }

# 3) Βιβλιοθήκες — reinstall όταν αλλάζει το requirements.txt (π.χ. νέα εξάρτηση)
$depsFlag = Join-Path $here ".venv\.deps_ok"
$reqFile  = Join-Path $here "requirements.txt"
$needDeps = $true
if (Test-Path $depsFlag) {
    try { $needDeps = (Get-Item $reqFile).LastWriteTimeUtc -gt (Get-Item $depsFlag).LastWriteTimeUtc } catch { $needDeps = $true }
}
if ($needDeps) {
    Write-Host "[3/4] Εγκατάσταση/ενημέρωση βιβλιοθηκών (Flask, Playwright, Pillow, pywebview, pdfplumber)..." -ForegroundColor Yellow
    & $venvPy -m pip install --upgrade pip | Out-Null
    & $venvPy -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) { Write-Host "[!] Αποτυχία βιβλιοθηκών" -ForegroundColor Red; Read-Host "Enter"; exit 1 }
    "ok" | Out-File -Encoding ascii $depsFlag
} else { Write-Host "[3/4] Βιβλιοθήκες: εντάξει" -ForegroundColor Green }

# 3β) Chromium (ΠΡΟΑΙΡΕΤΙΚΟ — αλλιώς χρησιμοποιείται ο Edge των Windows)
$browserFlag = Join-Path $here ".venv\.browser_ok"
if (-not (Test-Path $browserFlag)) {
    Write-Host "    Κατέβασμα Chromium (προαιρετικό)..." -ForegroundColor Yellow
    $ok = $false
    for ($i=1; $i -le 3; $i++) { & $venvPy -m playwright install chromium; if ($LASTEXITCODE -eq 0) { $ok=$true; break }
        Write-Host "    προσπάθεια $i απέτυχε..." -ForegroundColor DarkYellow; Start-Sleep -Seconds 3 }
    if ($ok) { "ok" | Out-File -Encoding ascii $browserFlag; Write-Host "    Chromium: εντάξει" -ForegroundColor Green }
    else { Write-Host "    [i] Δεν κατέβηκε — θα χρησιμοποιηθεί ο Edge των Windows. Κανένα πρόβλημα." -ForegroundColor DarkYellow }
}

# 4) Συντόμευση (native παράθυρο)
Write-Host "[4/4] Συντόμευση στην Επιφάνεια Εργασίας..." -ForegroundColor Yellow
try {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Price Compare.lnk'
    $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $venvPyw; $sc.Arguments = '"' + (Join-Path $here 'desktop.py') + '"'
    $sc.WorkingDirectory = $here
    $ico = Join-Path $here 'app.ico'; if (Test-Path $ico) { $sc.IconLocation = $ico } else { $sc.IconLocation = "$venvPyw,0" }
    $sc.Save()
} catch { Write-Host "    (συντόμευση παραλείφθηκε)" -ForegroundColor DarkYellow }

Write-Host "`n[OK] Έτοιμο! Ανοίγει η εφαρμογή...`n" -ForegroundColor Green
$app = Join-Path $here 'desktop.py'
if ($Browser) { Start-Process -FilePath $venvPy  -ArgumentList "`"$app`"","--browser" -WorkingDirectory $here }
else          { Start-Process -FilePath $venvPyw -ArgumentList "`"$app`""             -WorkingDirectory $here }
Start-Sleep -Seconds 2
exit 0
