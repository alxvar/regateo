#!/usr/bin/env bash
# Run Claude Code as the climb proposer on a workspace from `regateo workspace` (docs/04-hill-climbing.md §5.2).
#
#   scripts/claude_proposer.sh WORKSPACE [MODEL]        # MODEL defaults to claude-sonnet-5-5
#
# Isolation: bubblewrap shows it the system's programs (read-only) and the workspace, nothing else: not this
# repo, not your home folder, not your SSH or GitHub keys. Its home is an empty temp folder holding only your
# Claude Code login, so it uses your subscription. It keeps network access, which it needs for the Claude API;
# the repo is private, so without keys it can't fetch it. No MCP servers, no user settings, hooks or memory.
# Permissions: dontAsk, so anything not in --allowedTools is refused rather than asked about: file tools, and
# shell commands only for python3 and a few read-only ones. Python can still do anything the sandbox allows;
# the sandbox, not the tool list, is what keeps it away from the repo.
#
# Writes WORKSPACE/claude-run.json: the final message, turns, duration and token usage (to see what a round
# costs of the allowance).
set -euo pipefail

WS=$(realpath "$1")
MODEL=${2:-claude-sonnet-5-5}
CLAUDE=${CLAUDE_BIN:-$(command -v claude || ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude | sort -V | tail -1)}
CREDS="$HOME/.claude/.credentials.json"
[[ -f "$WS/README.md" ]] || { echo "$WS is not a proposer workspace (no README.md)" >&2; exit 1; }
[[ -f "$CREDS" ]] || { echo "no Claude Code login at $CREDS" >&2; exit 1; }

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
  --bind "$SANDBOX_HOME" /home/proposer \
  --bind "$CREDS" /home/proposer/.claude/.credentials.json \
  --ro-bind "$CLAUDE" /opt/claude \
  --bind "$WS" /work --chdir /work \
  --unshare-pid --unshare-ipc --unshare-uts --die-with-parent \
  --clearenv --setenv HOME /home/proposer --setenv PATH /usr/bin --setenv TERM dumb \
  /opt/claude -p "Read README.md in this folder and do the task it describes. Work only inside this folder." \
    --model "$MODEL" \
    --tools Read Glob Grep Write Edit Bash \
    --permission-mode dontAsk \
    --allowedTools Read Glob Grep Write Edit "Bash(python3 *)" "Bash(ls *)" "Bash(wc *)" "Bash(head *)" \
      "Bash(tail *)" "Bash(jq *)" \
    --strict-mcp-config --setting-sources "" \
    --no-session-persistence \
    --output-format json \
  > "$WS/claude-run.json"

python3 -c "
import json, sys
r = json.load(open(sys.argv[1]))
u = r.get('usage', {})
print(f\"turns {r.get('num_turns')}, {r.get('duration_ms', 0) / 60000:.1f} min, \"
      f\"input {u.get('input_tokens', 0)} + cache read {u.get('cache_read_input_tokens', 0)} \"
      f\"+ cache write {u.get('cache_creation_input_tokens', 0)}, output {u.get('output_tokens', 0)} tokens\")
" "$WS/claude-run.json"
ls "$WS/candidates"
