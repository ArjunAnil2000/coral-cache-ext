#!/usr/bin/env bash
# Copy the cache_ext API headers and a few reference policies from the
# third_party/cache_ext submodule into seed/reference/, so the agent can read
# them inside its own worktree (agents only see a copy of seed/). Re-run after
# bumping the submodule.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/third_party/cache_ext/policies"
DST="$REPO/seed/reference"
[[ -d "$SRC" ]] || { echo "submodule third_party/cache_ext not initialised" >&2; exit 1; }
rm -rf "$DST"; mkdir -p "$DST"
cp "$SRC"/cache_ext_lib.bpf.h "$SRC"/dir_watcher.bpf.h "$SRC"/dir_watcher.h "$DST"/
for p in s3fifo sampling get_scan fifo mglru lhd mru; do
  cp "$SRC/cache_ext_$p.bpf.c" "$SRC/cache_ext_$p.c" "$DST"/
done
[[ -f "$SRC/cache_ext_lhd.bpf.h" ]] && cp "$SRC/cache_ext_lhd.bpf.h" "$DST"/
cat > "$DST/README.md" <<'EOT'
Reference material (read-only; NOT graded). Headers + reference policies from the
cache_ext project: `*.bpf.c` = kernel side, `*.c` = userspace loader. Your policy is
the single combined file `noop.c` (see the task description for its format).
EOT
echo "synced $(ls "$DST" | wc -l) files into $DST"
