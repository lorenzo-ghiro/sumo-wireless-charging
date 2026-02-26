#!/usr/bin/env bash
set -euo pipefail

mkdir -p results

DISTRIB="U(0.1,0.49)-U(0.5,1.0)"
VUTISOCL=1e-4
SEED="$1"

# 3 traffic rates x 2 vut x 2 mpcInterval = 12 simulations
flow_files=(
    "flow_2_4_vpm5_VUT60.xml"
    "flow_2_4_vpm5_VUT0.xml"
    "flow_11_13_vpm12_VUT60.xml"
    "flow_11_13_vpm12_VUT0.xml"
    "flow_16_18_vpm20_VUT60.xml"
    "flow_16_18_vpm20_VUT0.xml"
)

for fname in "${flow_files[@]}"; do
    flowxml="src/flows/$fname"
    
    if [[ ! -f "$flowxml" ]]; then
        echo "File not found: $flowxml" >&2
        continue
    fi

    # Parse start and end times from the filename
    if [[ "$fname" =~ ^flow_([0-9]+)_([0-9]+)_ ]]; then
        start="${BASH_REMATCH[1]}"
        end="${BASH_REMATCH[2]}"
    else
        echo "Filename not recognized: $fname" >&2
        continue
    fi

    base_name="${fname#flow_}"
    base_name="${base_name%.xml}"
    
    # Compute fromt: 15 minutes after begin (1 hour after start)
    fromt_h=$((start + 1))
    fromt="${fromt_h}:00:00"
    
    for mpcInterval in 5 -5; do
        out_prefix="results/seed_${SEED}_${base_name}_${DISTRIB}_mpcInterval_${mpcInterval}_VUTIL_${VUTISOCL}_"
        echo ". python runner.py --seed ${SEED} --flowfile \"src/vtypes.xml,src/flows/$fname\" --distrib \"${DISTRIB}\" --begin \"${start}:45:00\" --end \"${end}:00:00\" --fromt \"${fromt}\" --output-prefix \"$out_prefix\" --mpcInterval $mpcInterval --vutisocl $VUTISOCL --nogui"
    done
done
