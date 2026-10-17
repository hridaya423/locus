#!/bin/sh
# Prepares a fresh worktree of this repository to run: shared data, secrets, Python env and web dependencies.
# Usage: sh scripts/worktree-setup.sh   (from the worktree root)
set -e
MAIN=${LOCUS_MAIN:-/Users/hridyaagrawal/.t3/projects/sciencefinder}
[ -e data ] || ln -s "$MAIN/data" data
[ -e .env ] || cp "$MAIN/.env" .env
[ -d web/node_modules ] || cp -cR "$MAIN/web/node_modules" web/node_modules
uv sync -q
