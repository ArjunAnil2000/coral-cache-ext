#!/usr/bin/env bash
# install_remote.sh <ssh_target> [key_path]
#
# Run from the CORAL host. One-time (idempotent) setup of the SSH eval backend:
#   1. generates a dedicated passphrase-less key (default ~/.ssh/coral_eval_ed25519)
#   2. copies remote/eval_remote.py to the node (/mydata/evo_cache/coral-remote/)
#   3. appends the public key to the node's ~/.ssh/authorized_keys as a
#      FORCED-COMMAND key: it can only run eval_remote.py (as root via sudo -n),
#      with no pty/forwarding (`restrict`). Agents that read this key (they run
#      on this host) therefore get no shell on the node.
#
# Uses your normal ssh credentials for steps 2-3 (not the new key).
set -euo pipefail

TARGET="${1:?usage: install_remote.sh <user@host> [key_path]}"
KEY="${2:-$HOME/.ssh/coral_eval_ed25519}"
REMOTE_DIR=/mydata/evo_cache/coral-remote
HERE="$(cd "$(dirname "$0")" && pwd)"
FORCED='sudo -n env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin python3.11 '"$REMOTE_DIR"'/eval_remote.py'

[[ -f "$KEY" ]] || ssh-keygen -t ed25519 -N '' -C coral-eval -f "$KEY" >/dev/null
PUB="$(cat "$KEY.pub")"

ssh "$TARGET" "mkdir -p $REMOTE_DIR"
scp -q "$HERE/eval_remote.py" "$TARGET:$REMOTE_DIR/eval_remote.py"

LINE="command=\"$FORCED\",restrict $PUB"
ssh "$TARGET" "mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && \
  { grep -qF '$(awk '{print $2}' "$KEY.pub")' ~/.ssh/authorized_keys || printf '%s\n' '$LINE' >> ~/.ssh/authorized_keys; }"

echo "installed. grader.args: ssh_target=$TARGET ssh_key=$KEY"
echo "smoke test: echo '{}' | ssh -i $KEY -o IdentitiesOnly=yes $TARGET x   # expect a JSON {\"status\":\"error\"...}"
