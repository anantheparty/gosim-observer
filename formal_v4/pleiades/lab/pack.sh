#!/bin/bash
# usage: pack.sh <srcdir> <name>  -> packages/<name>.zip
SRC=$1; NAME=$2
OUT=/home/shu/kamico/observer/work/packages/$NAME
rm -rf $OUT $OUT.zip; mkdir -p $OUT
cp $SRC/agent.py $SRC/policy.py $SRC/astro.py $SRC/kern.c $SRC/libkern_linux_x86_64.so $SRC/observer.project.json $OUT/
[ -f $SRC/policy_params.json ] && cp $SRC/policy_params.json $OUT/
echo "numpy==2.2.6" > $OUT/requirements.txt
python3 - "$OUT" <<'PY'
import sys, zipfile, os
out = sys.argv[1]
with zipfile.ZipFile(out + '.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for name in sorted(os.listdir(out)):
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 5, 0, 0, 0))
        info.external_attr = (0o755 if name.endswith('.so') else 0o644) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, open(os.path.join(out, name), 'rb').read())
PY
sha256sum $OUT.zip; python3 -c "import zipfile,sys;[print(i.filename,i.file_size) for i in zipfile.ZipFile(sys.argv[1]).infolist()]" $OUT.zip
