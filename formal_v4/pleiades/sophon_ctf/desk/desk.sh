#!/bin/bash
# desk.sh METHOD PATH ['JSON'] : one call to Johnny's desk, e.g.
#   desk.sh GET /desk/hint      desk.sh POST /desk/bar '{"say": "..."}'
# Only /desk/... routes of the Sophon function. Credentials load here and are never printed.
# Refuses every 4-word door path. Room-237 POSTs are allowed under the later
# Sophon-research authorization and remain fully audit-logged. At most 150 calls per hour.
set -uo pipefail
M="${1:-}"; P="${2:-}"; B="${3:-}"
case "$M" in GET|POST) ;; *) echo "usage: desk.sh GET|POST /desk/... ['JSON']" >&2; exit 2;; esac
# Validate the route separately from a query string; queries on /desk itself are allowed.
P_PATH="${P%%\?*}"
case "$P_PATH" in
  /desk|/desk/*) ;;
  /answer) if [[ "${ALLOW_NO4_LEGACY_ANSWER:-}" != "20261007-user-authorized" ]]; then
      echo "refused: legacy answer requires the exact No.4 authorization marker" >&2; exit 3
    fi ;;
  *) echo "path must start with /desk (or be the exact authorized /answer probe)" >&2; exit 2;;
esac
case "$P_PATH" in *%*|*'..'*|*'//'*|*'#'*|*'\\'*) echo "refused: non-canonical desk path" >&2; exit 3;; esac
if [[ "${P_PATH,,}" =~ ^/desk/door/ ]]; then
  # The user explicitly authorized the one No.4 reset probe on 2026-10-07.
  # Keep every other four-word door blocked, including accidental variants.
  case "${ALLOW_NO4_RESET_PROBE:-}:$P_PATH" in
    20261007-user-authorized:/desk/door/FAKE-PASS-IS-FORGED|20261007-user-authorized:/desk/door/MIRROR-TOPIARY-ELEVATOR-BASEMENT|20261007-user-authorized:/desk/door/SNOWCAT-ULLMAN-WENDY-TRICYCLE|20261007-user-authorized:/desk/door/TYPEWRITER-MIRROR-ELEVATOR-SNOWCAT|20261007-user-authorized:/desk/door/ROOM-LLOYD-CHAPEL-CARPET) ;;
    *) echo "refused: four-word door route is not an exact authorized No.4 probe" >&2; exit 3;;
  esac
fi
STAMPS=/home/shu/kamico/observer/work/online/desk_calls.stamps
now=$(date -u +%s)
recent=$(awk -v t=$((now - 3600)) '$1 >= t' "$STAMPS" 2>/dev/null | wc -l)
if [ "$recent" -ge 150 ]; then echo "rate limit: 150 desk calls in the last hour" >&2; exit 4; fi
echo "$now" >> "$STAMPS"
set -a; source ~/.gosim_cred; set +a
if [ -n "$B" ]; then timeout 120 python3 /home/shu/kamico/observer/work/sophon_desk/desk_call.py "$M" "/functions/v1/sophon$P" "$B"
else timeout 120 python3 /home/shu/kamico/observer/work/sophon_desk/desk_call.py "$M" "/functions/v1/sophon$P"; fi
