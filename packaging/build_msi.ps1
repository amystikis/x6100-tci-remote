# Build a Windows installer (.msi) from the PyInstaller folder. Run build_windows.ps1 first, then from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging\build_msi.ps1
# Needs the .NET SDK (preinstalled on GitHub's Windows runners); the WiX tool is installed as a dotnet tool.
$ErrorActionPreference = "Stop"
$ver = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
if (-not (Test-Path dist\x6100-tci-remote\x6100-tci-remote.exe)) { throw "run packaging\build_windows.ps1 first" }
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    dotnet tool install --global wix --version 5.0.2
    $env:PATH += ";$env:USERPROFILE\.dotnet\tools"
}
New-Item -ItemType Directory -Force build | Out-Null
$msi = "build\x6100-tci-remote_${ver}_windows.msi"
wix build packaging\windows\product.wxs -arch x64 -d Version=$ver -d SourceDir=dist\x6100-tci-remote `
    -d IconFile=packaging\x6100-tci-remote.ico -o $msi
if ($LASTEXITCODE -ne 0) { throw "wix build failed" }
Write-Host "Wrote $msi"
