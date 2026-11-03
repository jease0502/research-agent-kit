#!/usr/bin/env bash
# Start Claude Code inside the L1 sandbox (README.md). Linux, macOS, WSL2, and Git Bash on Windows.
#
#   RAK_PROJECT=/abs/project RAK_KIT=/abs/research-agent-kit RAK_AUDIT=/abs/outside/audit \
#     templates/sandbox/run.sh build                      # build the image (once per Claude Code version)
#   ... run.sh claude [claude args...] < prompt.txt       # one non-interactive run, prompt on stdin
#   ... run.sh shell                                      # a shell in the agent container, for checking by hand
#   ... run.sh exec CMD...                                # one command in a fresh agent container (verify.py)
#   ... run.sh down                                       # stop the proxy and the audit collector
#
# RAK_MODE=copy (default): the project is copied into a fresh volume (no .git, no protected paths); the agent works
#   there; afterwards the changes are written as a patch to $RAK_AUDIT/runs/<time>/changes.patch. Nothing on the host
#   changes until you review it and `git apply -p1` it. A patch touching a protected path is refused whole (exit 3).
# RAK_MODE=mount: the project folder itself, read-write with read-only overlays. Only on a case-sensitive filesystem
#   (Linux, WSL2 ext4); changed protected files are quarantined and restored (exit 3).
#
# Auth: set CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`) or ANTHROPIC_API_KEY in your own environment, e.g.
# from a file under ~/.config. Nothing here reads the host's ~/.claude.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MSYS_NO_PATHCONV=1                       # Git Bash: do not rewrite /work, /opt/... into Windows paths
TAG="${RAK_SANDBOX_TAG:-2.1.316}"
IMAGE="rak-sandbox:$TAG"
export RAK_SANDBOX_TAG="$TAG"
export RAK_EGRESS_ALLOW="${RAK_EGRESS_ALLOW:-api.anthropic.com arxiv.org export.arxiv.org}"
MODE="${RAK_MODE:-copy}"
case "$MODE" in copy|mount) ;; *) echo "run.sh: RAK_MODE must be copy or mount" >&2; exit 2;; esac
PY=""
for c in python3 python; do                     # skip Windows' Store alias, which exists but does not run
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || { echo "run.sh: needs Python 3 on the host (for host.py)" >&2; exit 2; }

hostpath() {                                    # Docker Desktop on Windows wants D:/x, not /d/x
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}
HOSTPY="$(hostpath "$HERE/host.py")"
host() { "$PY" "$HOSTPY" "$@"; }
stamp() { date +%Y%m%d-%H%M%S; }

CLEAN=()
cleanup_all() { local c; for c in "${CLEAN[@]+"${CLEAN[@]}"}"; do eval "$c" >/dev/null 2>&1 || true; done; }
trap cleanup_all EXIT

need() {
  local out
  # realpath, case-insensitive where the filesystem is; refuses a drive root, your home, nesting (host.py check)
  out="$(host check "$(hostpath "${RAK_PROJECT:-}")" "$(hostpath "${RAK_KIT:-}")" "$(hostpath "${RAK_AUDIT:-}")")" \
    || exit 2
  { read -r RAK_PROJECT; read -r RAK_KIT; read -r RAK_AUDIT; } <<<"$out"
  export RAK_PROJECT RAK_KIT RAK_AUDIT
  [ "$MODE" = mount ] && { host mountfs "$RAK_PROJECT" || exit 2; }
  return 0
}

compose() { docker compose -f "$(hostpath "$HERE")/compose.yaml" "$@"; }
oneoff() {                                      # a helper container: no network, no privileges
  docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges "$@"
}

in_copy() {                                     # run "$@" (a compose run) against a fresh copy of the project
  local vol tars out rc=0 rc2=0
  vol="rak-ws-$(stamp)-$RANDOM"
  tars="$(mktemp -d)"
  CLEAN+=("docker volume rm -f $vol" "rm -rf '$tars'")
  docker volume create "$vol" >/dev/null
  host pack "$RAK_PROJECT" "$(hostpath "$tars/base.tar")"
  oneoff -v "$vol:/work" "$IMAGE" tar -x -C /work < "$tars/base.tar"
  "$@" -e RAK_MODE=copy -v "$vol:/work" agent "${AGENT_CMD[@]}" || rc=$?
  oneoff -v "$vol:/work:ro" "$IMAGE" tar -c -C /work . > "$tars/new.tar"
  out="$RAK_AUDIT/runs/$(stamp)-$RANDOM"
  # Judged from the tar entries on the host (never extracted there: the host filesystem may fold names together);
  # 3 = refused, 4 = changes that may be applied, 0 = none.
  host inspect "$(hostpath "$tars/base.tar")" "$(hostpath "$tars/new.tar")" "$(hostpath "$out")" || rc2=$?
  if [ "$rc2" -eq 4 ]; then
    rc2=0                                       # the patch is written by git inside a container, on a tmpfs
    oneoff --tmpfs /tmp:size=1g -v "$(hostpath "$tars"):/in:ro" "$IMAGE" sh -c \
      'mkdir /tmp/a /tmp/b && tar -x -C /tmp/a -f /in/base.tar && tar -x -C /tmp/b -f /in/new.tar && cd /tmp &&
       git -c core.quotepath=off diff --no-index --binary --no-prefix --no-renames a b; [ $? -le 1 ]' \
      > "$out/changes.patch" || { echo "run.sh: writing the patch failed" >&2; rc2=1; }
    echo "SANDBOX: changes are in $out/changes.patch (see summary.json). Review, then in the project:" >&2
    echo "  git apply -p1 '$out/changes.patch'" >&2
  fi
  [ "$rc2" -ne 0 ] && return "$rc2"
  return "$rc"
}

in_mount() {                                    # run "$@" against the project folder itself, then undo protected changes
  local empty store made quar rc=0 rc2=0 ro
  empty="$(mktemp -d)"; store="$(mktemp -d)"; made="$(mktemp)"
  CLEAN+=("rmdir '$empty'" "rm -rf '$store'" "rm -f '$made'")
  mapfile -t ro < <(host mounts "$RAK_PROJECT" "$(hostpath "$empty")")
  host missing "$RAK_PROJECT" > "$made"
  host backup "$RAK_PROJECT" "$(hostpath "$store")"
  "$@" -e RAK_MODE=mount -v "$RAK_PROJECT:/work" "${ro[@]}" agent "${AGENT_CMD[@]}" || rc=$?
  host cleanup "$RAK_PROJECT" "$(hostpath "$made")"
  quar="$RAK_AUDIT/quarantine/$(stamp)-$RANDOM"
  host restore "$RAK_PROJECT" "$(hostpath "$store")" "$quar" || rc2=$?
  [ "$rc2" -ne 0 ] && return "$rc2"
  return "$rc"
}

run_agent() {                                   # run_agent <compose run flags...> -- <command in the agent>
  local flags=()
  while [ "$1" != "--" ]; do flags+=("$1"); shift; done; shift
  AGENT_CMD=("$@")
  if [ "$MODE" = copy ]; then in_copy compose run --rm "${flags[@]}"; else in_mount compose run --rm "${flags[@]}"; fi
}

case "${1:-}" in
  build)
    docker build --build-arg "CLAUDE_CODE_VERSION=$TAG" -t "$IMAGE" "$(hostpath "$HERE")"
    ;;
  claude)
    shift; need
    if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
      echo "run.sh: set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY (the host's login is not shared)" >&2; exit 2
    fi
    # --tools "": no built-in tool, only the four mcp__rak__* tools (docs/mcp-server.md §4).
    # --restricted and --setting-sources= : no user, project or local settings file is read, so nothing the agent
    # wrote into its home or the project can add a hook (review of 6555c3c, H2). Only --settings applies.
    run_agent -T -- claude -p --tools "" --restricted --setting-sources= \
      --settings /opt/rak-config/settings.json --mcp-config /opt/rak-config/mcp.json --strict-mcp-config "$@"
    ;;
  shell)
    shift; need; run_agent -- bash "$@"
    ;;
  exec)
    shift; need; run_agent -T -- "$@"
    ;;
  down)
    RAK_AUDIT="${RAK_AUDIT:-$HERE}" compose down --remove-orphans
    ;;
  *)
    sed -n '2,19p' "$0"; exit 2
    ;;
esac
