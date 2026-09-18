#!/bin/sh
set -eu
commit=d97587f669b4f169be7132346df70e7d634500c3
work="${TMPDIR:-/tmp}/signoff-opensta-$commit"
if ! docker image inspect signoff-opensta-base:d97587f >/dev/null 2>&1; then
  rm -rf "$work"
  git clone --filter=blob:none https://github.com/The-OpenROAD-Project/OpenSTA.git "$work"
  git -C "$work" checkout --detach "$commit"
  docker build -f "$work/Dockerfile.ubuntu24.04" -t signoff-opensta-base:d97587f "$work"
fi
docker build -f backend/Dockerfile.sta-worker -t signoff-sta-worker:d97587f backend
