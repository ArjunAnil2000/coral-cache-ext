#!/usr/bin/env bash
# node/install_remote.sh <ssh_target> [key_path] [node_root]
#
# Run from the CORAL host. Idempotent. Sets up the SSH eval backend:
#   1. generates a dedicated passphrase-less key (default ~/.ssh/coral_eval_ed25519)
#   2. rsyncs this repo (node/, third_party/ -- not results/, .git, .coral) to the
#      node at node_root (default /mydata/coral-cache-evolution)
#   3. installs the public key in the node's ~/.ssh/authorized_keys as a
#      FORCED-COMMAND key: it can only run node/eval_remote.py (as root via
#      sudo -n), with no pty/forwarding (`restrict`). Agents that read this
#      key (they run on this host) therefore get no shell on the node. An
#      older entry for the same key (e.g. an old install path) is replaced.
#
# Uses your normal ssh credentials for steps 2-3 (not the new key).
# Prereq: third_party/cache_ext (and its vulcan_bpf) submodules initialised locally:
#   git submodule update --init third_party/cache_ext
#   git -C third_party/cache_ext submodule update --init vulcan_bpf
set -euo pipefail

TARGET="${1:?usage: install_remote.sh <user@host> [key_path] [node_root]}"
KEY="${2:-$HOME/.ssh/coral_eval_ed25519}"
NODE_ROOT="${3:-/mydata/coral-cache-evolution}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
FORCED='sudo -n env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin python3.11 '"$NODE_ROOT"'/node/eval_remote.py'

[[ -f "$REPO/third_party/cache_ext/policies/Makefile" ]] || { echo "submodule third_party/cache_ext not initialised" >&2; exit 1; }
[[ -f "$KEY" ]] || ssh-keygen -t ed25519 -N '' -C coral-eval -f "$KEY" >/dev/null
PUB="$(cat "$KEY.pub")"; BLOB="$(awk '{print $2}' "$KEY.pub")"

ssh "$TARGET" "sudo -n mkdir -p '$NODE_ROOT' && sudo -n chown \$(id -u):\$(id -g) '$NODE_ROOT'"
rsync -a --delete \
  --exclude='.git' --exclude='.coral' --exclude='results/' --exclude='__pycache__' \
  --exclude='*.egg-info' --exclude='litellm-creds.sh' --exclude='cloudlab-instances.md' \
  --exclude='third_party/cache_ext/linux' --exclude='third_party/cache_ext/rocksdb' \
  --exclude='third_party/cache_ext/My-YCSB-scan' --exclude='third_party/cache_ext/leveldb' \
  "$REPO/" "$TARGET:$NODE_ROOT/"

LINE="command=\"$FORCED\",restrict $PUB"
ssh "$TARGET" "mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && \
  grep -vF '$BLOB' ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.new || true; \
  printf '%s\n' '$LINE' >> ~/.ssh/authorized_keys.new && mv ~/.ssh/authorized_keys.new ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

echo "deployed to $TARGET:$NODE_ROOT"
echo "grader.args: ssh_target=$TARGET ssh_key=$KEY remote_command=<forced; see task.yaml>"
echo "next on a node that has never run get_scan: ssh $TARGET $NODE_ROOT/node/bench/get_scan/setup.sh setup"
