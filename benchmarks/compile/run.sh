#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."

runs=${1:-11}
case $runs in *[!0-9]*|'') echo "usage: $0 [runs] [--check]" >&2; exit 2;; esac
check=${2:-}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
mkdir -p "$work/app" "$work/dependency" "$work/cache"
cp tests/manifest-app/main.dyn tests/manifest-app/dyn.project "$work/app/"
cp tests/manifest-dependency/library.dyn "$work/dependency/"
sed -i 's#../manifest-dependency#../dependency#' "$work/app/dyn.project"

measure() {
  label=$1; shift
  values="$work/$label.values"; : > "$values"
  i=0
  while [ "$i" -lt "$runs" ]; do
    start=$(date +%s%N); "$@" >/dev/null; end=$(date +%s%N)
    awk -v a="$start" -v b="$end" 'BEGIN { printf "%.3f\n", (b-a)/1000000 }' >> "$values"
    i=$((i+1))
  done
  sort -n "$values" | sed -n "$((runs / 2 + 1))p"
}

export DYN_CACHE_DIR="$work/cache"
cold_values="$work/cold.values"; : > "$cold_values"
i=0
while [ "$i" -lt "$runs" ]; do
  rm -rf "$work/cache" "$work/app.out" "$work/app.out.dyncache" "$work/app.out.dyncache.files"
  mkdir -p "$work/cache"
  start=$(date +%s%N); ./build/dyn build "$work/app" --output "$work/app.out" --quiet; end=$(date +%s%N)
  awk -v a="$start" -v b="$end" 'BEGIN { printf "%.3f\n", (b-a)/1000000 }' >> "$cold_values"
  i=$((i+1))
done
cold=$(sort -n "$cold_values" | sed -n "$((runs / 2 + 1))p")

./build/dyn build "$work/app" --output "$work/app.out" --quiet
warm=$(measure warm ./build/dyn build "$work/app" --output "$work/app.out" --quiet)
private_values="$work/private.values"; : > "$private_values"
i=0
while [ "$i" -lt "$runs" ]; do
  printf '\n// private edit %s\n' "$i" >> "$work/dependency/library.dyn"
  start=$(date +%s%N); ./build/dyn build "$work/app" --output "$work/app.out" --quiet; end=$(date +%s%N)
  awk -v a="$start" -v b="$end" 'BEGIN { printf "%.3f\n", (b-a)/1000000 }' >> "$private_values"
  i=$((i+1))
done
private=$(sort -n "$private_values" | sed -n "$((runs / 2 + 1))p")

printf 'case\tmedian_ms\nclean\t%s\nwarm\t%s\nprivate_edit\t%s\n' "$cold" "$warm" "$private"
if [ "$check" = "--check" ]; then
  awk -v cold="$cold" -v warm="$warm" 'BEGIN { exit !(warm * 1.5 < cold) }' || {
    echo "cached compile regression: warm must be at least 1.5x faster than clean" >&2; exit 1;
  }
fi
