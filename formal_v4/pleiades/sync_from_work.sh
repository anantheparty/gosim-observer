#!/bin/bash
# sync_from_work.sh [PKG] : copy the versioned part of the work tree into this directory.
#   agent/ <- work/packages/<PKG> (the exact submitted package; default o4e_c17w5) + harness_entry.py
#   lab/   <- harness, job runner, world generators, packers, analysis tools, world specs
# Run outputs, generated worlds, online downloads and credentials are never copied.
set -euo pipefail
PKG=${1:-o4h_c21b}
WORK=/home/shu/kamico/observer/work
HERE=$(cd "$(dirname "$0")" && pwd)
[ -d "$WORK/packages/$PKG" ] || { echo "no package $WORK/packages/$PKG" >&2; exit 1; }
rm -rf "$HERE/agent" "$HERE/lab"
mkdir -p "$HERE/agent" "$HERE/lab/tools" "$HERE/lab/hspec"
cp "$WORK/packages/$PKG"/* "$HERE/agent/"
# the pkgs/ source directory of the package (same policy and parameters) supplies the harness entry point
src=""
for d in "$WORK"/pkgs/*/; do
  d=${d%/}
  if cmp -s "$d/policy.py" "$WORK/packages/$PKG/policy.py" && \
     cmp -s "$d/policy_params.json" "$WORK/packages/$PKG/policy_params.json"; then
    src=$d; break
  fi
done
if [ -n "$src" ]; then cp "$src/harness_entry.py" "$HERE/agent/"; fi
for f in harness.py qrun3.py mkjobs.py pack.sh dockertest.sh dockertest2.sh dockertest3.sh dockertest4.sh batch.sh rbatch.sh rstat.sh rfetch.sh \
         lstat.sh runcard.sh sweep.sh genworld.py gen_formal_like.py gen_hidden_like.py gen_hidden_like2.py gen_weird.py gen_event.py mkred.py \
         analyze_run.py table.py table2.py table3.py; do
  cp "$WORK/$f" "$HERE/lab/"
done
cp "$WORK"/tools/*.py "$HERE/lab/tools/"
cp -r "$WORK"/hspec/* "$HERE/lab/hspec/"
(cd "$HERE/agent" && sha256sum ./* > ../agent.sha256)
echo "synced $PKG from ${src:-?}"
