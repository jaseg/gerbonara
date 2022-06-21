#!/bin/sh

set -e 
git clone /data/git git
cd git
#python3 -m pytest --workers auto
python3 -m pytest -x

