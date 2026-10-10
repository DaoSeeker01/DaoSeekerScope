param(
    [string]$VcRoot,
    [string]$SdkRoot,
    [string]$SdkVersion
)
$ErrorActionPreference = 'Stop'
if (!$VcRoot) {
    $VcRoot = $env:VCToolsInstallDir
    if (!$VcRoot) {
        $vswhereCommand = Get-Command vswhere.exe -ErrorAction SilentlyContinue
        $vswhere = if ($vswhereCommand) { $vswhereCommand.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe' }
        if (!(Test-Path -LiteralPath $vswhere)) { throw 'vswhere not found; pass -VcRoot' }
        $installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($LASTEXITCODE -ne 0 -or !$installation) { throw 'MSVC installation not found; pass -VcRoot' }
        $version = (Get-Content -LiteralPath (Join-Path $installation 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        $VcRoot = Join-Path $installation "VC\Tools\MSVC\$version"
    }
}
if (!$SdkRoot) {
    $SdkRoot = $env:WindowsSdkDir
    if (!$SdkRoot) { $SdkRoot = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots').KitsRoot10 }
}
if (!$SdkVersion) {
    $SdkVersion = Get-ChildItem -LiteralPath (Join-Path $SdkRoot 'Include') -Directory |
        Where-Object { $_.Name -match '^10\.0\.\d+\.\d+$' -and (Test-Path -LiteralPath (Join-Path $SdkRoot "Lib\$($_.Name)\um\x64")) } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1 -ExpandProperty Name
    if (!$SdkVersion) { throw 'Windows SDK not found; pass -SdkRoot and -SdkVersion' }
}
$compiler = Join-Path $VcRoot 'bin\Hostx64\x64\cl.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'MSVC not found; pass -VcRoot' }
$oldInclude = $env:INCLUDE
$oldLib = $env:LIB
$oldPath = $env:PATH
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:INCLUDE = @((Join-Path $VcRoot 'include'), (Join-Path $SdkRoot "Include\$SdkVersion\ucrt"), (Join-Path $SdkRoot "Include\$SdkVersion\shared"), (Join-Path $SdkRoot "Include\$SdkVersion\um")) -join ';'
    $env:LIB = @((Join-Path $VcRoot 'lib\x64'), (Join-Path $SdkRoot "Lib\$SdkVersion\ucrt\x64"), (Join-Path $SdkRoot "Lib\$SdkVersion\um\x64")) -join ';'
    $env:PATH = (Join-Path $VcRoot 'bin\Hostx64\x64') + ';' + $oldPath
    & $compiler /nologo /W4 /WX /std:c11 /Fetarget\debug\c-example.exe /Fotarget\debug\c-example.obj examples\collect.c target\debug\daoseeker_scope_ffi.dll.lib
    if ($LASTEXITCODE -ne 0) { throw "C compile failed: $LASTEXITCODE" }
    & .\target\debug\c-example.exe | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "C ABI smoke failed: $LASTEXITCODE" }
    Write-Output 'C ABI: real collect/free, zeroing, empty free and stale copy rejection passed'
} finally {
    $env:INCLUDE = $oldInclude
    $env:LIB = $oldLib
    $env:PATH = $oldPath
    Pop-Location
}
