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
         analyze_run.py table.py table2.py table3.py gen_adv.py anaonline.py cmpv5.py cmpfinal.py mk_final_jobs.sh cmp28.py pollbatch.py \
         cmp29.py addlog.py movefault.py seasonfit.py mkguider.py mkvariantworld.py engine_g_v4_scorer.patch; do
  cp "$WORK/$f" "$HERE/lab/"
done
# handover-log tests (A1-D1 logs from online result zips; synthetic log worlds come from addlog.py)
mkdir -p "$HERE/lab/logtest"
cp "$WORK"/logtest/*.py "$WORK"/logtest/*.json "$HERE/lab/logtest/"
# log-variant corpus: review notes and patches only (the generated variant logs and worlds are rebuilt by variants.py)
mkdir -p "$HERE/lab/logtest/variants"
cp "$WORK"/logtest/variants/*.txt "$WORK"/logtest/variants/*.patch "$WORK"/logtest/variants/manifest.json "$HERE/lab/logtest/variants/"
# round-2/3 red-team battery (world specs for gen_adv.py) and its parallel builder
mkdir -p "$HERE/lab/adv2"
cp "$WORK"/adv2/battery.py "$WORK"/adv2/build.py "$HERE/lab/adv2/"
cp "$WORK"/tools/*.py "$HERE/lab/tools/"
cp -r "$WORK"/hspec/* "$HERE/lab/hspec/"
(cd "$HERE/agent" && sha256sum ./* > ../agent.sha256)
echo "synced $PKG from ${src:-?}"
