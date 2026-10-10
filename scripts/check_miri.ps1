param()
$ErrorActionPreference = 'Stop'
$nightly = '+nightly-2026-10-08'
# Cross-interpret pure memory contracts; this does not test native Linux APIs.
$oldIncremental = $env:CARGO_INCREMENTAL
$oldTarget = $env:CARGO_TARGET_DIR
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:CARGO_INCREMENTAL = '0'
    $env:CARGO_TARGET_DIR = 'target/miri-contracts-fixed'
    & cargo $nightly miri test --locked -p daoseeker-scope-ffi --target x86_64-unknown-linux-gnu memory_contracts -- --test-threads=1
    if ($LASTEXITCODE -ne 0) { throw "Miri failed: $LASTEXITCODE" }
} finally {
    $env:CARGO_INCREMENTAL = $oldIncremental
    $env:CARGO_TARGET_DIR = $oldTarget
    Pop-Location
}
