#!/usr/bin/env bash
# Refresh the cache_ext API headers in seed/reference/ from the third_party/cache_ext
# submodule (re-run after bumping the submodule). The seed policy (seed/noop.c, S3-FIFO)
# is a hand-maintained combined file and is NOT touched here.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/third_party/cache_ext/policies"
DST="$REPO/seed/reference"
[[ -d "$SRC" ]] || { echo "submodule third_party/cache_ext not initialised" >&2; exit 1; }
cp "$SRC"/cache_ext_lib.bpf.h "$SRC"/dir_watcher.bpf.h "$SRC"/dir_watcher.h "$DST"/
echo "refreshed headers in $DST"
