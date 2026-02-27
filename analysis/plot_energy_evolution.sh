#!/bin/bash
# Generate energy vs time comparison plots for all scenarios

RESULTS_DIR="../results"

echo "=========================================="
echo "Generating energy evolution plots..."
echo "=========================================="

# Scenario 2-4h (vpm5)
echo -e "\n[1/3] Scenario 2-4h (fromt=3:00:00)..."
python energyVStime_comparator.py \
  --bench ${RESULTS_DIR}/seed_0_2_4_vpm5_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_-5_VUTIL_1e-4_battery.out.parquet \
  --opt ${RESULTS_DIR}/seed_0_2_4_vpm5_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_battery.out.parquet \
  --tripinfo ${RESULTS_DIR}/seed_0_2_4_vpm5_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_tripinfo.out.parquet \
  --fromt 3:00:00

# Scenario 11-13h (vpm12)
echo -e "\n[2/3] Scenario 11-13h (fromt=12:00:00)..."
python energyVStime_comparator.py \
  --bench ${RESULTS_DIR}/seed_0_11_13_vpm12_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_-5_VUTIL_1e-4_battery.out.parquet \
  --opt ${RESULTS_DIR}/seed_0_11_13_vpm12_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_battery.out.parquet \
  --tripinfo ${RESULTS_DIR}/seed_0_11_13_vpm12_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_tripinfo.out.parquet \
  --fromt 12:00:00

# Scenario 16-18h
echo -e "\n[3/3] Scenario 16-18h (fromt=17:00:00)..."
python energyVStime_comparator.py \
  --bench ${RESULTS_DIR}/seed_0_16_18_vpm20_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_-5_VUTIL_1e-4_battery.out.parquet \
  --opt ${RESULTS_DIR}/seed_0_16_18_vpm20_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_battery.out.parquet \
  --tripinfo ${RESULTS_DIR}/seed_0_16_18_vpm20_VUT60_U\(0.1,0.49\)-U\(0.5,1.0\)_mpcInterval_5_VUTIL_1e-4_tripinfo.out.parquet \
  --fromt 17:00:00

echo -e "\n=========================================="
echo "Done! Generated PDFs:"
echo "  - energyVStime_s0_2-4h_vpm5_VUT60.pdf"
echo "  - energyVStime_s0_11-13h_vpm12_VUT60.pdf"
echo "  - energyVStime_s0_16-18h_vpm20_VUT60.pdf"
echo "=========================================="
