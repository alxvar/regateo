#!/usr/bin/env bash
# Run Claude Code as the builder for one architecture in a climb round, on a workspace from
# `regateo round export --venv` (regateo.climb.round, docs/06-agent-contract.md §5).
#
#   scripts/claude_builder.sh WORKSPACE [MODEL]          # MODEL defaults to claude-sonnet-5-5
#
# Several in parallel, one per architecture:
#   for ws in ROUND_DIR/*/; do scripts/claude_builder.sh "$ws" & done; wait
#
# Isolation, as scripts/claude_proposer.sh: bubblewrap shows it the system's programs (read-only), the
# workspace, the DNS resolver's folder (/etc/resolv.conf links into /run/systemd/resolve) and the Python
# installs its .venv points to (read-only), nothing else: not this repo, not the engine, not other
# architectures, not your home folder or keys. The workspace is mounted at its own path, so the .venv's
# scripts (pytest, regateo-agent) work; the .venv holds only the agent SDK and pytest. Its home is
# an empty temp folder with only your Claude Code login. It keeps network access, which it needs for the API.
# Permissions: dontAsk, so anything not in --allowedTools is refused: file tools, and shell commands only for
# the workspace's python, pytest and regateo-agent, and a few read-only ones.
#
# Writes WORKSPACE/claude-run.json: the final message, turns, duration and token usage.
set -euo pipefail

WS=$(realpath "$1")
MODEL=${2:-claude-sonnet-5-5}
CLAUDE=${CLAUDE_BIN:-$(command -v claude || ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude | sort -V | tail -1)}
CREDS="$HOME/.claude/.credentials.json"
[[ -f "$WS/.regateo-round.json" ]] || { echo "$WS is not a round workspace (no .regateo-round.json)" >&2; exit 1; }
[[ -x "$WS/.venv/bin/python" ]] || { echo "$WS has no .venv: export it with --venv" >&2; exit 1; }
[[ -f "$CREDS" ]] || { echo "no Claude Code login at $CREDS" >&2; exit 1; }
# The interpreter the .venv points to: under /usr it is already visible; uv's managed installs are reached
# through a version symlink (cpython-3.11-... -> cpython-3.11.16-...), so their whole folder is bound.
PYBIN=$(realpath "$WS/.venv/bin/python")
case "$PYBIN" in
  /usr/*) PYBIND=() ;;
  *) PYROOT=$(dirname "$(dirname "$(dirname "$PYBIN")")"); PYBIND=(--ro-bind "$PYROOT" "$PYROOT") ;;
esac

SANDBOX_HOME=$(mktemp -d)
trap 'rm -rf "$SANDBOX_HOME"' EXIT
mkdir -p "$SANDBOX_HOME/.claude"
touch "$SANDBOX_HOME/.claude/.credentials.json"
echo '{"hasCompletedOnboarding": true}' > "$SANDBOX_HOME/.claude.json"

bwrap \
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --symlink usr/sbin /sbin --ro-bind /etc /etc \
  --ro-bind-try /run/systemd/resolve /run/systemd/resolve \
  --proc /proc --dev /dev --tmpfs /tmp \
  --bind "$SANDBOX_HOME" /home/builder \
  --bind "$CREDS" /home/builder/.claude/.credentials.json \
  --ro-bind "$CLAUDE" /opt/claude \
  "${PYBIND[@]}" \
  --bind "$WS" "$WS" --chdir "$WS" \
  --unshare-pid --unshare-ipc --unshare-uts --die-with-parent \
  --clearenv --setenv HOME /home/builder --setenv PATH "$WS/.venv/bin:/usr/bin" --setenv TERM dumb \
  /opt/claude -p "Read README.md in this folder and do the task it describes. Work only inside this folder." \
    --model "$MODEL" \
    --tools Read Glob Grep Write Edit Bash \
    --permission-mode dontAsk \
    --allowedTools Read Glob Grep Write Edit "Bash(python *)" "Bash(python3 *)" "Bash(pytest *)" \
      "Bash(regateo-agent *)" "Bash(cp *)" "Bash(mkdir *)" "Bash(ls *)" "Bash(wc *)" "Bash(head *)" \
      "Bash(tail *)" "Bash(jq *)" "Bash(diff *)" \
    --strict-mcp-config --setting-sources "" \
    --no-session-persistence \
    --output-format json \
  > "$WS/claude-run.json"

python3 -c "
import json, sys
r = json.load(open(sys.argv[1]))
u = r.get('usage', {})
print(f\"{sys.argv[2]}: turns {r.get('num_turns')}, {r.get('duration_ms', 0) / 60000:.1f} min, \"
      f\"input {u.get('input_tokens', 0)} + cache read {u.get('cache_read_input_tokens', 0)} \"
      f\"+ cache write {u.get('cache_creation_input_tokens', 0)}, output {u.get('output_tokens', 0)} tokens\")
" "$WS/claude-run.json" "$(basename "$WS")"
