#!/usr/bin/env bash
set -euo pipefail

echo "Generating 6 flows: low/medium/intense traffic x2 (with and without VUT)"

echo "=== Flows WITH VUT (60s interval) ==="
python genFlows.py --begin 2 --end 4 --vpm 5 --vutinterval 60
python genFlows.py --begin 11 --end 13 --vpm 12 --vutinterval 60
python genFlows.py --begin 16 --end 18 --vpm 20 --vutinterval 60

echo "=== Flows WITHOUT VUT ==="
python genFlows.py --begin 2 --end 4 --vpm 5 --novut
python genFlows.py --begin 11 --end 13 --vpm 12 --novut
python genFlows.py --begin 16 --end 18 --vpm 20 --novut

echo "All flows generated."
