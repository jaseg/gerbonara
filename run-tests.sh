#!/bin/sh

set -e

rm -rf podman/testdata/git
git clone --depth 1 . podman/testdata/git

for distro in arch ubuntu
do
    podman build -t gerbonara-$distro-testenv -f podman/$distro-testenv
    mkdir -p /tmp/gerbonara-test-out
    podman run --mount type=bind,src=podman/testdata,dst=/data,ro --mount type=bind,src=/tmp/gerbonara-test-out,dst=/out gerbonara-$distro-testenv /data/testscript.sh
done

