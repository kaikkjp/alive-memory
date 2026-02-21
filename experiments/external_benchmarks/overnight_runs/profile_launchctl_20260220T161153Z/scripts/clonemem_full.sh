#!/bin/zsh
set -euo pipefail
set -a
source /Users/user/Documents/Tokyo-Arc/product/alive/.env
set +a
/usr/local/bin/python3 /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/tools/run_clonemem_full.py --retrieve-k 50 --embedding-model all-MiniLM-L6-v2 --num-workers 1 >> /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/overnight_runs/profile_launchctl_20260220T161153Z/logs/clonemem_full.log 2>&1
