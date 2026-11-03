#!/usr/bin/env bash
# Link candidates in the same pinned Debian 12 userland used by runtime tests.
# Native Rust tests still run on Ubuntu 24.04. Only trusted source is built here.
set -euo pipefail
product=${1:-cli}
case "$product" in cli|ffi_sdk) ;; *) echo 'expected cli or ffi_sdk' >&2; exit 2;; esac
workspace=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$workspace"
toolchain=$(realpath "$(rustc --print sysroot)")
cargo_cache=$(realpath "${CARGO_HOME:-$HOME/.cargo}")
read -r image expected_id <<< "$(python -c 'import sys; sys.path.insert(0, "scripts"); from linux_runtime_container_smoke import PROFILES; p = PROFILES["bookworm"]; print(p["image"], p["config_digest"])')"
docker pull --platform linux/amd64 "$image" >&2
test "$(docker image inspect --format '{{.Id}} {{.Architecture}} {{.Os}}' "$image")" = "$expected_id amd64 linux"
name="dscope-build-$(python -c 'import uuid; print(uuid.uuid4().hex)')"
docker create --name "$name" --platform linux/amd64 \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 4g --pids-limit 256 --cpus 2 --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --mount "type=bind,src=$workspace,dst=$workspace" \
  --mount "type=bind,src=$toolchain,dst=$toolchain,readonly" \
  --mount "type=bind,src=$cargo_cache,dst=$cargo_cache" \
  --workdir "$workspace" --env "CARGO_HOME=$cargo_cache" \
  --env "PATH=$toolchain/bin:/usr/local/bin:/usr/bin:/bin" \
  --env CARGO_NET_OFFLINE=true --env CARGO_BUILD_JOBS=2 \
  --entrypoint /bin/bash "$image" --noprofile --norc -c \
  'set -e; test "$(getconf GNU_LIBC_VERSION)" = "glibc 2.36"; exec python scripts/cli_bundle.py --offline --product "$1"' _ "$product" >/dev/null
cleanup() {
  local result=$?
  if ! docker rm --force "$name" >/dev/null; then
    echo 'candidate build container cleanup failed' >&2
    exit 1
  fi
  exit "$result"
}
trap cleanup EXIT
timeout --signal=TERM --kill-after=5s 600s docker start --attach "$name"
test "$(docker inspect --format '{{.State.ExitCode}}' "$name")" = 0
