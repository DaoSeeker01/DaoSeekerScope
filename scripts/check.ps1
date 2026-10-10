param([switch]$Cross)
$ErrorActionPreference = 'Stop'
$oldIncremental = $env:CARGO_INCREMENTAL
$oldRustdoc = $env:RUSTDOCFLAGS
function Invoke-Cargo {
    param([string[]]$CargoArguments)
    & cargo @CargoArguments
    if ($LASTEXITCODE -ne 0) { throw "cargo failed ($LASTEXITCODE): $CargoArguments" }
}
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:CARGO_INCREMENTAL = '0'
    $env:RUSTDOCFLAGS = '-D warnings'
    Invoke-Cargo -CargoArguments @('fmt', '--all', '--check')
    Invoke-Cargo -CargoArguments @('clippy', '--locked', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings')
    Invoke-Cargo -CargoArguments @('test', '--locked', '--workspace', '--all-features', '--', '--test-threads=1')
    Invoke-Cargo -CargoArguments @('check', '--locked', '-p', 'daoseeker-scope-core', '--no-default-features')
    Invoke-Cargo -CargoArguments @('check', '--locked', '-p', 'daoseeker-scope', '--no-default-features')
    Invoke-Cargo -CargoArguments @('doc', '--locked', '--workspace', '--all-features', '--no-deps')
    Invoke-Cargo -CargoArguments @('build', '--locked', '-p', 'daoseeker-scope-ffi', '-p', 'daoseeker-scope-cli')
    if ($Cross) {
        Invoke-Cargo -CargoArguments @('check', '--locked', '--workspace', '--all-features', '--target', 'x86_64-unknown-linux-gnu')
        Invoke-Cargo -CargoArguments @('check', '--locked', '--workspace', '--all-features', '--target', 'aarch64-apple-darwin')
    }
} finally {
    $env:CARGO_INCREMENTAL = $oldIncremental
    $env:RUSTDOCFLAGS = $oldRustdoc
    Pop-Location
}
