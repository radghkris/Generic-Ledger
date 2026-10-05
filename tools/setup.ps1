# Generic Ledger - one-step setup and updater (Windows PowerShell 5.1+).
#   setup.ps1           install / repair: files, Python (if missing), desktop shortcut, launch
#   setup.ps1 -Update   quiet update-if-newer, used by run_desktop.bat; never touches your data
param(
    [switch]$Update,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

$Repo    = 'radghkris/Generic-Ledger'
$Branch  = 'main'
$Default = Join-Path $env:LOCALAPPDATA 'GenericLedger'

# Run from inside an installed/cloned copy -> work on that copy; otherwise use the default folder.
$here = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $null }
$App  = if ($here -and (Test-Path (Join-Path $here 'desktop_app.py'))) { $here } else { $Default }
$IsGitClone = Test-Path (Join-Path $App '.git')
$StampFile  = Join-Path $App '.version'

function Say($msg) { if (-not $Update) { Write-Host $msg } }

function Get-LatestSha {
    $h = @{ 'Accept' = 'application/vnd.github.sha'; 'User-Agent' = 'GenericLedger' }
    (Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$Branch" -Headers $h -TimeoutSec 10).ToString().Trim()
}

function Sync-Files {
    $sha = $null
    try { $sha = Get-LatestSha } catch { }
    $current = if (Test-Path $StampFile) { (Get-Content $StampFile -Raw).Trim() } else { '' }
    if ($sha -and $sha -eq $current -and (Test-Path (Join-Path $App 'desktop_app.py'))) {
        Say 'Already up to date.'
        return
    }
    if ($IsGitClone) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) { Push-Location $App; try { & git pull --quiet } finally { Pop-Location } }
        return
    }
    Say 'Downloading the latest version...'
    $tmp = Join-Path $env:TEMP ("ledger_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'src.zip'
        Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip -UseBasicParsing -TimeoutSec 60
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
        New-Item -ItemType Directory -Path $App -Force | Out-Null
        # Copy code over the install; leave the user's data and logs alone.
        & robocopy $src.FullName $App /E /XF ledger_data.json error_log.txt .version /XD .git .venv /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "File copy failed (robocopy code $LASTEXITCODE)." }
        if ($sha) { Set-Content -Path $StampFile -Value $sha }
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Find-Pythonw {
    foreach ($n in 'pythonw', 'pyw') {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        # Skip the Microsoft Store stub that opens the Store instead of running Python.
        if ($c -and $c.Source -notlike '*\WindowsApps\*') { return $c.Source }
    }
    $hit = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python') -Filter pythonw.exe -Recurse -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

function Install-Python {
    Say 'Python was not found - installing it now (a minute or two)...'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
    }
    if (-not (Find-Pythonw)) {
        $exe = Join-Path $env:TEMP 'python-installer.exe'
        Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile $exe -UseBasicParsing
        Start-Process $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_tcltk=1' -Wait
        Remove-Item $exe -ErrorAction SilentlyContinue
    }
    # Refresh PATH for this session so the new Python is visible.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function New-DesktopShortcut {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Generic Ledger.lnk'
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = Join-Path $App 'run_desktop.bat'
    $sh.WorkingDirectory = $App
    $sh.WindowStyle = 7
    $sh.Description = 'Generic Ledger'
    $sh.Save()
}

try {
    Sync-Files
    if ($Update) { exit 0 }

    if (-not (Find-Pythonw)) { Install-Python }
    if (-not (Find-Pythonw)) { throw 'Python could not be installed automatically. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run this again.' }

    New-DesktopShortcut
    Write-Host ''
    Write-Host "Done. A 'Generic Ledger' shortcut is on your Desktop."
    if (-not $NoLaunch) { Start-Process (Join-Path $App 'run_desktop.bat') -WorkingDirectory $App }
} catch {
    if ($Update) { exit 0 }   # update problems (offline etc.) must never block starting the app
    Write-Host ''
    Write-Host "Setup problem: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
