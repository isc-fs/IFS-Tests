# Sourced by deploy.sh and restore.sh, after they set $env, $dir and their die/log functions.
# shellcheck shell=bash disable=SC2154

# One deploy or restore at a time per environment.
lock=$dir/operation.lock
lock_check() {
  [[ -d $lock ]] || return 0
  die "$(cat "$lock/what" 2>/dev/null || echo "a deploy or restore") is already running in $env; if none is" \
    "(ps aux | grep -E 'deploy|restore', after a reboot for example), rm -r $lock"
}
lock_take() {
  mkdir "$lock" 2>/dev/null || { lock_check; die "can't create $lock"; }
  echo "$1 (log: ${QUIZ_LOG:-none})" >"$lock/what"
}
lock_release() { rm -rf "$lock"; }

# Runs this script again with the same arguments on its own (nohup, its own process group), logging to
# $dir/<name>-<date>-<time>.log, and follows that log: a dropped SSH session, Ctrl-C or killing this script only
# stops the view. Exits with the worker's status. The worker sees QUIZ_DETACHED=1.
run_detached() {
  local name=$1 logfile worker watcher status=0
  shift
  logfile=$dir/$name-$(TZ=Europe/Madrid date +%Y%m%d-%H%M%S).log
  set -m # its own process group: a signal to this terminal's group doesn't reach it
  QUIZ_DETACHED=1 QUIZ_LOG=$logfile nohup bash "$0" "$@" </dev/null >>"$logfile" 2>&1 &
  worker=$!
  set +m
  log "running on its own: a dropped connection or Ctrl-C only stops this view. Log: $logfile"
  tail -n +1 -f "$logfile" &
  watcher=$!
  # Stops the view when the worker ends or when this script is killed, so it never outlives both.
  (while kill -0 $$ 2>/dev/null && kill -0 "$worker" 2>/dev/null; do sleep 1; done; sleep 1; kill "$watcher" 2>/dev/null) &
  wait "$worker" || status=$?
  sleep 1
  kill "$watcher" 2>/dev/null || true
  exit "$status"
}
