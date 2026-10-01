#!/usr/bin/env bash
# Run by publish.yml before it builds a release image. Refuses unless the tag is the version in pyproject.toml,
# its commit is on main, and CI passed on that commit (waiting for a run still in progress).
# Usage: release-gate.sh <tag> <commit> <owner/repo>; needs `gh` with a token that can read Actions.
set -euo pipefail

tag=${1:?tag} sha=${2:?commit} repo=${3:?owner/repo}
tries=${GATE_TRIES:-60} wait=${GATE_WAIT:-30}
die() { echo "release-gate: $*" >&2; exit 1; }

[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "$tag isn't vX.Y.Z"
version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
[[ $tag == "v$version" ]] || die "$tag doesn't match version = \"$version\" in pyproject.toml"

git fetch -q origin main
git merge-base --is-ancestor "$sha" origin/main || die "$sha isn't on main: tag the merge commit of the release pull request"

for ((i = 1; i <= tries; i++)); do
  run=$(gh api "repos/$repo/actions/workflows/ci.yml/runs?head_sha=$sha&branch=main&event=push" \
    --jq '.workflow_runs[0] | if . == null then "none" else .status + " " + (.conclusion // "") end')
  case $run in
    "completed success") echo "release-gate: $tag at $sha is on main and passed CI"; exit 0 ;;
    completed*) die "CI on $sha ended ${run#completed }: fix main and tag a new patch version" ;;
  esac
  echo "release-gate: CI on $sha: $run (check $i of $tries)"
  sleep "$wait"
done
die "no successful CI run on $sha after $((tries * wait)) s: when CI is green, re-run this workflow"
