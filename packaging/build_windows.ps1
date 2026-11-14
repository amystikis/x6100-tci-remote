# Build a standalone Windows folder (and zip) with PyInstaller. Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
$ver = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
python -m pip install --upgrade pip
python -m pip install ".[gui]" pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name x6100-tci-remote `
    --paths src --collect-submodules x6100_remote --icon packaging\x6100-tci-remote.ico `
    packaging\windows_entry.py
Copy-Item LICENSE, README.md dist\x6100-tci-remote\
New-Item -ItemType Directory -Force build | Out-Null
$zip = "build\x6100-tci-remote_${ver}_windows.zip"
Compress-Archive -Path dist\x6100-tci-remote -DestinationPath $zip -Force
Write-Host "Wrote $zip"
