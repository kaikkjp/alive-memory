#!/bin/zsh
set -euo pipefail
set -a
source /Users/user/Documents/Tokyo-Arc/product/alive/.env
set +a
/usr/local/bin/python3 /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/tools/run_memoryagentbench_full.py --force >> /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/overnight_runs/profile_at_20260220T160102Z/logs/memoryagentbench_full.log 2>&1
