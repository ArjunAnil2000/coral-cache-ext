#!/usr/bin/env bash
# node/setup_node.sh -- provision a FRESH CloudLab node for the SSH eval backend.
#
# Run ON the node, from the deployed repo (node/install_remote.sh puts it at
# $NODE_ROOT, default /mydata/coral-cache-evolution). Only needed for a node
# that does not already have the cache-ext kernel + toolchain; an already
# provisioned node just needs node/install_remote.sh.
#
# Phases:
#   (default)         1) fetch the kernel source submodule, install the
#                        6.6.8-cache-ext+ kernel, grub-reboot into it, reboot
#   --post-reboot     2) apt deps (python3.11, clang-14, cgroup-tools, bench
#                        build deps), build the reference policies (sanity),
#                        build the get_scan benchmark stack
#
# Pinned submodule revisions are fetched with plain `git clone` because the
# deployed copy has no .git (it is rsync'd). Keep these in sync with the
# third_party/cache_ext submodule's own pins (`git submodule status` there).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
CACHE_EXT="$ROOT/third_party/cache_ext"
LINUX_URL=https://github.com/cache-ext/linux-cache-ext.git;  LINUX_REV=7442a927600ec6ded8ad56a708d293f7cb0d303d
LEVELDB_URL=https://github.com/cache-ext/leveldb.git;        LEVELDB_REV=66f3f5b84d827defdbeb60bc62af7a2d86c18668

log() { echo "[$(date +%H:%M:%S)] $*"; }

clone_pinned() { # url rev dest
    if [[ -n "$(ls -A "$3" 2>/dev/null)" ]]; then log "$3 already populated"; return; fi
    mkdir -p "$3"
    git clone --quiet "$1" "$3"
    git -C "$3" checkout --quiet "$2"
}

phase_kernel() {
    log "phase 1: kernel"
    # CloudLab sites like wisc block plain-HTTP apt mirrors but allow HTTPS.
    sudo sed -i 's#http://#https://#g' /etc/apt/sources.list
    sudo sed -i 's#http://#https://#g' /etc/apt/sources.list.d/*.list 2>/dev/null || true
    sudo apt-get update
    sudo mkdir -p "$(dirname "$ROOT")"; sudo chown -R "$(whoami)" "$ROOT"
    clone_pinned "$LINUX_URL" "$LINUX_REV" "$CACHE_EXT/linux"
    # install_kernel.sh prompts; answers: 1, Y, 1, N
    (cd "$CACHE_EXT" && printf '1\nY\n1\nN\n' | bash ./install_kernel.sh)
    sudo grub-reboot 'Advanced options for Ubuntu>Ubuntu, with Linux 6.6.8-cache-ext+'
    log "kernel installed; rebooting. Re-run with --post-reboot afterwards."
    sudo reboot now
}

phase_post_reboot() {
    log "phase 2: toolchain ($(uname -r))"
    [[ "$(uname -r)" == *cache-ext* ]] || log "WARNING: not running a cache-ext kernel"
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils \
        clang-14 cgroup-tools build-essential cmake unzip libsnappy-dev pkg-config wget git zstd
    clone_pinned "$LEVELDB_URL" "$LEVELDB_REV" "$CACHE_EXT/leveldb"
    (cd "$CACHE_EXT" && bash ./build_policies.sh)          # sanity: toolchain compiles policies
    bash "$HERE/bench/get_scan/setup.sh" setup            # yaml-cpp, leveldb, My-YCSB(leveldb-scan)
    sudo mkdir -p /run/evo_cache
    log "done. From the dev host: node/install_remote.sh (if not yet run), then coral validate."
}

case "${1:-}" in
    --post-reboot) phase_post_reboot ;;
    "") phase_kernel ;;
    *) echo "usage: $0 [--post-reboot]" >&2; exit 2 ;;
esac
