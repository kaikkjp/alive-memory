#!/bin/zsh
set -euo pipefail
set -a
source /Users/user/Documents/Tokyo-Arc/product/alive/.env
set +a
/usr/local/bin/python3 /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/tools/run_ultrahorizon_scaled.py --steps 50 --n-experiments 32 --max-concurrency 4 --window-size 64 --env seq --index overnight --exp-folder codex_overnight >> /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/overnight_runs/profile_launchctl_20260220T161153Z/logs/ultrahorizon_heavy.log 2>&1
