#!/bin/zsh
set -euo pipefail
set -a
source /Users/user/Documents/Tokyo-Arc/product/alive/.env
set +a
/usr/local/bin/python3 /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/tools/run_maj_eval_batch.py --db-path /Users/user/Documents/Tokyo-Arc/product/alive/data/shopkeeper_live.db --source-table events --max-samples 100 --visitor-id ALL --jury-profile persona --model openai/gpt-4o-mini --voting-method average >> /Users/user/Documents/Tokyo-Arc/product/alive/experiments/external_benchmarks/overnight_runs/profile_launchctl_20260220T161153Z/logs/maj_eval_persona_100.log 2>&1
