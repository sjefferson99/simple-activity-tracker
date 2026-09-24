#!/usr/bin/env sh
# Prints the release version for the current checkout — docs/VERSIONING.md §1.
#   exactly on tag v1.3.0      -> 1.3.0
#   4 commits past v1.3.0      -> 1.3.0+4.gabc1234
#   no release tag reachable   -> 0.0.0+gabc1234
# Needs the tags in the clone (CI: actions/checkout with fetch-depth: 0).
set -eu

describe=$(git describe --tags --long --match 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || true)
if [ -z "$describe" ]; then
  echo "0.0.0+g$(git rev-parse --short HEAD)"
  exit 0
fi

# v1.3.0-4-gabc1234 -> tag=v1.3.0, count=4, sha=gabc1234
sha=${describe##*-}
rest=${describe%-*}
count=${rest##*-}
tag=${rest%-*}
base=${tag#v}

if [ "$count" = "0" ]; then
  echo "$base"
else
  echo "$base+$count.$sha"
fi
