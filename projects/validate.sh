#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$project_root"
DYN=${DYN:-$(command -v dyn || true)}
if test -z "$DYN"; then
  if test -x ../build/dyn; then DYN="$project_root/../build/dyn"
  elif test -x ../compiler/build/dyn; then DYN="$project_root/../compiler/build/dyn"
  else echo 'Set DYN to an installed or built compiler' >&2; exit 2; fi
fi
BUILD=${BUILD:-"$project_root/build"}
mkdir -p "$BUILD"
BUILD=$(CDPATH= cd -- "$BUILD" && pwd)
export DYN
python3 tools/check.py
if test -f ../tests/vendor-packages.py; then
  (cd .. && python3 tests/vendor-packages.py)
  (cd .. && python3 tests/vendor-extra.py)
else
  echo 'Workspace provider integration suite not present; running standalone project checks'
fi

for project in memory-tour example multi-module field-notes panic json-check recursive-search process-supervisor http-server http-client websocket-server websocket-client tar-inspect raw-terminal; do
  "$DYN" build "$project" --release --output "$BUILD/project-$project" >/dev/null
done

"$BUILD/project-memory-tour"
"$BUILD/project-example" >/dev/null
test "$(printf quit | "$BUILD/project-field-notes" | tail -n 1)" = '> goodbye; permanent bytes used: 2588'

sqlite=
for candidate in /usr/lib/libsqlite3.so /usr/lib/x86_64-linux-gnu/libsqlite3.so /lib/x86_64-linux-gnu/libsqlite3.so; do
  if test -e "$candidate"; then sqlite=$candidate; break; fi
done
if test -n "$sqlite"; then
  "$DYN" build sqlite-example --release --output "$BUILD/project-sqlite-example" >/dev/null
  "$BUILD/project-sqlite-example"
  "$DYN" build db-stuff --release --output "$BUILD/project-db-stuff" >/dev/null
  "$BUILD/project-db-stuff" >/dev/null
else
  if test "${DYN_REQUIRE_ALL:-0}" = 1; then echo "Required project provider missing" >&2; exit 1; fi
  echo 'sqlite skipped: shared library unavailable'
fi

if pkg-config --exists sdl3 2>/dev/null; then
  sdl3_library=$(pkg-config --variable=libdir sdl3)/libSDL3.so
  if test -e "$sdl3_library"; then
    if test -f ../tests/sdl3-loop.py; then (cd .. && python3 tests/sdl3-loop.py); fi
    "$DYN" build sdl3-example --release --output "$BUILD/project-sdl3-example" >/dev/null
    "$DYN" build sdl3-audio-example --release --output "$BUILD/project-sdl3-audio-example" >/dev/null
    "$DYN" build sdl3-gpu-example --release --output "$BUILD/project-sdl3-gpu-example" >/dev/null
    "$DYN" build window --release --output "$BUILD/project-window" >/dev/null
    # The window example now intentionally waits for a user close event.
    SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=dummy "$BUILD/project-sdl3-audio-example"
    # GPU lifecycle runs through sdl3-loop.py; dummy has no GPU driver.
  else
    if test "${DYN_REQUIRE_ALL:-0}" = 1; then echo "Required project provider missing" >&2; exit 1; fi
    echo 'SDL3 skipped: unversioned shared library unavailable'
  fi
else
  if test "${DYN_REQUIRE_ALL:-0}" = 1; then echo "Required project provider missing" >&2; exit 1; fi
  echo 'SDL3 skipped: pkg-config package unavailable'
fi

mkdir -p "$BUILD/project-search"
printf 'needle\n' > "$BUILD/project-search/match.txt"
test "$("$BUILD/project-recursive-search" "$BUILD/project-search" needle)" = "$BUILD/project-search/match.txt"
test "$("$BUILD/project-process-supervisor" /bin/true)" != ''

tar -cf "$BUILD/project.tar" -C "$BUILD/project-search" match.txt
test "$("$BUILD/project-tar-inspect" "$BUILD/project.tar")" = 'match.txt'

"$BUILD/project-http-server" >/dev/null &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
sleep 0.1
"$BUILD/project-http-client" > "$BUILD/project-http-response"
wait "$server"
trap - EXIT
grep -q 'hello from dyn' "$BUILD/project-http-response"

"$BUILD/project-websocket-server" &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
sleep 0.1
test "$("$BUILD/project-websocket-client")" = 'hello websocket'
wait "$server"
trap - EXIT

if command -v script >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
  printf q | timeout 3 script -qec "\"$BUILD/project-raw-terminal\"" /dev/null \
    >"$BUILD/project-raw-terminal.out"
  grep -q 'raw mode: press q to quit' "$BUILD/project-raw-terminal.out"
fi
echo 'projects passed'
