#!/bin/sh

set -e 
git clone /data/git git
cd git

if [ $# -ge 1 -a "$1" = "--parallel" ]; then
    python3 -m pytest --workers auto
else
    python3 -m pytest -x
fi

