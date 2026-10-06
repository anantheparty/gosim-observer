#!/bin/bash
# mk_final_jobs.sh NAME : regression (47 standard worlds, same machine split as c21b) + adversarial re-runs
N=$1
L=/home/shu/kamico/observer/work/pkgs/$N
R=/home/trainer/obswork/pkgs/$N
: > jobs_${N}_local.txt; : > jobs_${N}_remote.txt
for w in FB1 FB2 FB3 FB4 HF1 HF2 HF3 HF4 HG1 HG2 HE1 HE2 HE3 HE4 HG3 HG4 FA1 FA2 FD1 FD2 FD3 FD4; do printf "$N\t$w\t$L\t{}\t1\n" >> jobs_${N}_local.txt; done
for w in X5 X1 X2 X3 X4 X6 X7 HN2 HN6 HN1 HN3 HN4 HN5 HN7 HN8 FM1 FM2 FM3 FM4 FM5 FM6 HH1 HH2 HH3 HH4; do printf "$N\t$w\t$R\t{}\t1\n" >> jobs_${N}_remote.txt; done
for w in JS2 JS3 JS5 JC4 JE1 JE1b JE1c JE5 JE11 JE13 JE14 JE2 JR1; do printf "${N}adv\t$w\t$L\t{}\t1\n" >> jobs_${N}_local.txt; done
wc -l jobs_${N}_local.txt jobs_${N}_remote.txt
