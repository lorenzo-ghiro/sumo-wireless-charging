#!/usr/bin/env bash
set -euo pipefail

MPCI_VALUES=(5)

for MPCI in "${MPCI_VALUES[@]}"; do

echo "Plotting WITHOUT VUT (VUT0) scenarios..."

python satis_distrib_plotter.py \
  --opt parquets/satisfaction_moments_s0_b16_e18_mpcInt${MPCI}_VUT0_opt.parquet \
  --benchmark parquets/satisfaction_moments_s0_b16_e18_mpcInt-${MPCI}_VUT0_benchmark.parquet \
  --output distrib_satisfaction_moments_s0_b16_e18_mpcInt${MPCI}_VUT0.pdf

echo "Plotting WITH VUT (VUT60) scenarios..."

python satis_distrib_plotter.py \
  --opt parquets/satisfaction_moments_s0_b16_e18_mpcInt${MPCI}_VUT60_opt.parquet \
  --benchmark parquets/satisfaction_moments_s0_b16_e18_mpcInt-${MPCI}_VUT60_benchmark.parquet \
  --output distrib_satisfaction_moments_s0_b16_e18_mpcInt${MPCI}_VUT60.pdf \
  --kind pdf

done