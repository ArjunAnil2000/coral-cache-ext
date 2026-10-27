#!/usr/bin/env bash
# One-shot setup for a multi-host evolution (one CORAL agent per CloudLab host); see setup_multihost.py --help.
#   scripts/setup_multihost.sh            # then: source ./litellm-creds.sh && coral start -c task.yaml
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setup_multihost.py" "$@"
