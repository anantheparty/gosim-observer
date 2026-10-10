#!/bin/bash
# wait for the REDRUM-M wrapper to exit, then evaluate the fibre-glyph package in the Sophon phase
while kill -0 218591 2>/dev/null; do sleep 15; done
echo "$(date -u +%FT%TZ) M wrapper done; starting glyph eval"
/home/shu/kamico/observer/work/sophon_desk/sophon_eval.sh /home/shu/kamico/observer/work/packages/o4s_sophon4_glyph.zip "Sophon REDRUM: letters written with the fibres, one per night"
echo "$(date -u +%FT%TZ) glyph wrapper exit $?"
