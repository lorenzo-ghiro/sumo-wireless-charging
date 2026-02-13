# Wireless Power Transfer Management Framework with SUMO

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![SUMO](https://img.shields.io/badge/SUMO-1.15%2B-green)](https://www.eclipse.org/sumo/)

**Model Predictive Control for Dynamic Wireless Charging Systems**

This repository contains the simulation framework and analysis tools for investigating optimized power allocation strategies in Dynamic Inductive Charging (DIC) systems for electric vehicles. The work implements and evaluates an MPC-based optimization approach that prioritizes vehicles with critical battery states, improving user satisfaction under resource scarcity.

## Overview

Dynamic Inductive Charging (DIC) enables electric vehicles to charge wirelessly while driving on equipped road segments. However, when demand exceeds available power capacity, uncoordinated allocation leads to suboptimal resource utilization and user dissatisfaction. 

This framework implements a **Model Predictive Control (MPC)** strategy that:
- Dynamically allocates power based on vehicle urgency (battery state and remaining travel time)
- Optimizes satisfaction fairness by prioritizing critical vehicles
- Enables dynamic power rebalancing across charging infrastructure stripes
- Provides comprehensive simulation and analysis tools using SUMO traffic simulator

### Key Features

- **MPC-based Power Allocation**: Convex quadratic programming formulation solved in real-time
- **Realistic Urban Scenario**: Istanbul Üsküdar topology with 10 DIC-equipped road segments
- **Flexible Traffic Modeling**: Configurable demand patterns (5-20 vehicles/min) with deterministic critical vehicle injection
- **Performance Metrics**: SOC fulfillment, satisfaction indices, energy delivery, power utilization
- **Reproducible Research**: Automated batch simulations, data processing pipelines, and visualization tools

### Scientific Context

This work is part of ongoing research on sustainable mobility and intelligent transportation systems. 
The framework enables system-level analysis of DIC performance under various operational strategies, traffic conditions, and infrastructure configurations.

**Related Publication**: *[Paper title and venue to be added upon acceptance]*

---

## Defining Flows

```bash
cd src
./genflows.sh
```
The shell script relies on [src/genFlows.py](src/genFlows.py) to generate SUMO flow definitions.

### Flow Generation Arguments:
```
--vpm VPM              Lambda: vehicles per minute per lane
--vtype VTYPE          (optional) Default "soulEV65"
--begin BEGIN          Begin time as hour of day (e.g., 17 for 17:00)
--end END              End time as hour of day (e.g., 18 for 18:00)
--vutinterval INT      Deterministic interval in seconds for spawning VUT vehicles (default: 60)
--novut                Skip generation of VUT (Vehicles Under Test) flows
```

**VUT (Vehicles Under Test)** are special deterministic vehicles spawned at fixed intervals (default: every 60 seconds) that:
- Enter the DIC area with nearly depleted batteries (SOC ≈ 0.0001)
- Desire full recharge (SOC_desired = 1.0)
- Follow the longest routes (NLe→ExitSL and SRe→ExitNR)
- Represent extreme charging urgency scenarios for testing system behavior under critical demand

The flow file naming convention is: `flow_{begin}_{end}_vpm{rate}_VUT{interval}.xml`
- VUT60: includes VUT vehicles every 60 seconds  
- VUT0: no VUT vehicles


## ChargingStations deployment

```
➜  cd src && python generate_cs.py \                 
  --net net.net.xml \ 
  --minedgelength 150 \
  --margin 0.05 \
  --policy full_lane0_lane1 \
  --out cs.add.xml \
  --nominalPower 100 \
  --powerbudget 16 \
  --efficiency 0.95
20 charginStations defined in cs.add.xml

Coveredspace=18.7km out of 19.3km of road_length
coverage of 96.94%
|    | edge      |   spire_length [m] |   totalPower [kW] |
|----|-----------|--------------------|-------------------|
|  0 | eN2S_4    |             978.00 |           1673.22 |
|  1 | eN2S_5    |             629.00 |           1076.13 |
|  2 | eN2S_8    |            1276.00 |           2183.06 |
|  3 | eS2N_4    |            1263.00 |           2160.82 |
|  4 | eS2N_7    |             628.00 |           1074.42 |
|  5 | eS2N_8    |             977.00 |           1671.51 |
|  6 | postNLe   |            1012.00 |           1731.39 |
|  7 | postSRe   |             795.00 |           1360.14 |
|  8 | preExitNR |            1009.00 |           1726.26 |
|  9 | preExitSL |             785.00 |           1343.03 |


```

The [generate_cs.py](/sources/generate_cs.py) script parse the net.xml file, detects edges longer than `minedgelength` (default 5m) and fully cover the 2 lanes with charging stations (policy `full_lane0_lane1`, more policies can be defined/implemented).
`--nominalPower` defaults to `100kW` is the maximum power of a coil composing a stripe (aka charging station).


## Running Simulations

### Single Simulation with GUI:
```bash
python runner.py \
  --seed 0 \
  --flowfile "src/vtypes.xml,src/flows/flow_16_18_vpm20_VUT60.xml" \
  --distrib "U(0.1,0.49)-U(0.5,1.0)" \
  --begin "16:45:00" \
  --end "18:00:00" \
  --fromt "17:00:00" \
  --output-prefix "results/test_" \
  --mpcInterval 5 \
  --vutisocl 1e-4
```

### Key Parameters:
- `--mpcInterval`: MPC optimization interval in seconds (positive value enables MPC, negative disables it for benchmark)
- `--distrib`: SOC distribution as "U(init_min,init_max)-U(des_min,des_max)"
  - Current setup: U(0.1,0.49)-U(0.5,1.0) means initial SOC in [0.1, 0.49], desired SOC in [0.5, 1.0]
- `--vutisocl`: Initial SOC level for VUT vehicles (default: 1e-4, nearly empty)
- `--fromt`: Time when MPC control starts (format: HH:MM:SS). Before this time, system runs in warmup mode.
- `--begin/--end`: Simulation time window
- `--nogui`: Run without graphical interface (faster)

### Batch Simulations:
Generate all simulation commands for a given seed: (requires [runmaker](https://github.com/veins/runmaker))
```bash
./printsim.sh 0
```
This generates commands for 12 simulations (3 time periods × 2 VUT settings × 2 strategies):
- **Time periods**: 2-4h (λ=5 vpm), 11-13h (λ=12 vpm), 16-18h (λ=20 vpm)
- **VUT settings**: VUT60 (with VUT vehicles every 60s), VUT0 (no VUT vehicles)
- **Strategies**: OPT (mpcInterval=5), Benchmark (mpcInterval=-5)

Execute the commands (example):
```bash
time runmaker4.py -j 0 runs
```
### Processing Satisfaction Data:
```bash
cd analysis
./satisProcess.sh    # Process all scenarios to generate satisfaction_moments parquets
```

### Generating Plots:

**Satisfaction Distribution (ECDF or PDF):**
```bash
python satis_distrib_plotter.py \
  --opt parquets/satisfaction_moments_*_opt.parquet \
  --benchmark parquets/satisfaction_moments_*_benchmark.parquet \
  --kind ecdf  # or 'pdf' for probability density function
```

**Multi-scenario ECDF Comparison:**
```bash  
python satis_ecdf_comparator.py \
  --folder parquets \
  --seed 0 \
  --mpcInterval 5 \
  --output satis_ecdf_comparison.pdf
```

**Power Evolution Plots:**
```bash
./plot_energy_evolution.sh
```

**Power Comparison Across Scenarios:**
```bash
python power_compare_plotter.py \
  --folder ../results \
  --seed 0 \
  --aggregation 20 \
  --vut 60 \
  --csxml ../src/cs.add.xml
```

### Key Performance Metrics:

1. **SOC Fulfillment** (φ_v): Ratio of achieved SOC to desired SOC at exit
   - φ_v = SOC_exit / SOC_desired ∈ [0, 1]
   - φ_v = 1 → complete satisfaction
   - φ_v < 1 → partial fulfillment

2. **Satisfaction Index** (SI): Feasibility-corrected satisfaction accounting for physical constraints (travel time, vehicle charging capacity, stripe power limits)

3. **Energy Delivered**: Total energy transferred to vehicles [MWh]

4. **Power Utilization**: Fraction of available DIC budget actively used

### Output Files:

Simulation outputs (in `results/`):
- `*_battery.out.parquet`: Battery state evolution (timestep, vid, SOC, charging station, energy consumed)
- `*_tripinfo.out.parquet`: Trip information (vid, depart, arrival, route, duration)
- `*_generated_vehs.parquet`: Vehicle parameters (vid, initial_soc, des_soc, exit_soc, Bmax)
- `*_cs_power_assigned.parquet`: Charging station power allocation over time
- `*_chargingstations.parquet`: Charging station activity logs

Analysis outputs (in `analysis/parquets/`):
- `satisfaction_moments_*.parquet`: Satisfaction metrics at departure and arrival for each vehicle
```

Without runmaker opt instead for the [dosim.sh](/dosim.sh) script:
```
./dosim.sh sources/sunday.rou.xml 100 20
```
This example runs with 100 different seed the sumo simulation loading the `sunday.rou.xml` demand file. 

If you want to run one selected simulation with gui
```
sumo-gui \
  -c istanbul.sumo.cfg \
  --route-files "sources/vtypes.xml,sources/sunday.rou.xml" \
  --seed 1234 \
  --output-prefix results/sunday/seed1234_
``` -->

## Analysis

```
cd analysis
make -j $(nproc)
```

The provided [Makefile](analysis/Makefile) automatically invokes `python $(SUMO_TOOLS)/xml/xml2csv.py` on all new xml files found in the dictated `SRC_DIR := ` that must be edited according to desired folder.
Currently it points to `../results/`
