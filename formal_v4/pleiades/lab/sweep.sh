#!/bin/bash
# sweep.sh <base_pkg_dir> <name> '<params json>' <local|remote> <worlds...>
BASE=$1; NAME=$2; PJ=$3; WHERE=$4; shift 4
D=/home/shu/kamico/observer/work/pkgs/$NAME
rm -rf $D; cp -r $BASE $D; rm -rf $D/__pycache__
echo "$PJ" > $D/policy_params.json
if [ "$WHERE" == "local" ]; then
  /home/shu/kamico/observer/work/batch.sh $NAME $D "$@"
else
  /home/shu/kamico/observer/work/rbatch.sh $NAME $D "$@"
fi
