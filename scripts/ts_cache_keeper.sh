#!/bin/sh
# Client-side tailscale cache keeper (Mac). Detects the 09-22 failure mode:
# duckdns record updated but Tailscale network-extension keeps dialing the
# stale cached AAAA. Detection: client health says broken AND control plane
# is actually reachable from the system → it's our cache, restart it.
# launchd com.aquant.tskeeper every 5 min. Rollback: bootout plist + rm script.
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
EP=https://zantao-home.duckdns.org:8443/key
LOG=$HOME/.hermes/stockdb/logs/tskeeper.log

ST=$("$TS" status 2>&1)
case "$ST" in
  *"logged out"*|*"Unable to connect to the Tailscale coordination server"*)
    CODE=$(curl -sk -m 8 -o /dev/null -w "%{http_code}" "$EP" 2>/dev/null)
    if [ "$CODE" != "000" ] && [ -n "$CODE" ]; then
      # server reachable but client claims otherwise → stale extension cache
      sudo -n dscacheutil -flushcache
      sudo -n pkill -HUP mDNSResponder
      EXT=$(pgrep -f io.tailscale.ipn.macsys.network-extension | head -1)
      [ -n "$EXT" ] && sudo -n kill -9 "$EXT"   # launchd respawns; keychain profile auto-logins
      echo "$(date '+%F %T') flushed+restarted ext=${EXT:-none} http=$CODE" >> "$LOG"
    else
      echo "$(date '+%F %T') degraded but control plane unreachable too (http=$CODE), left alone" >> "$LOG"
    fi ;;
esac
