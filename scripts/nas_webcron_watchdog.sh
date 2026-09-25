#!/bin/sh
# Mac-side: poke the NAS keeper every 5 min (launchd com.aquant.naskeeper).
# Fire-and-forget: keeper.sh on the NAS logs its own actions to
# /share/CACHEDEV1_DATA/headscale/keeper.log; waiting on its stdout hangs
# the ssh session whenever it actually restarts something (09-22 verified).
# NB: keep the word "webcron" out of this file — QTS busybox ps shows the
# full ssh command line and keeper greps ps output for it (self-match trap).
/usr/bin/ssh -n -o ConnectTimeout=8 -o BatchMode=yes zantao@nasgzt.local \
  'setsid /bin/sh /share/CACHEDEV1_DATA/headscale/keeper.sh </dev/null >>/share/CACHEDEV1_DATA/headscale/keeper.log 2>&1 &'
