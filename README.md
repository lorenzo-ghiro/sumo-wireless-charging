# Wireless Power Transfer Management Framework with SUMO

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![SUMO](https://img.shields.io/badge/SUMO-1.22%2B-green)](https://www.eclipse.org/sumo/)

**Model Predictive Control for Dynamic Wireless Charging Systems**

This repository contains the simulation framework and analysis tools for investigating optimized power allocation strategies in Dynamic Inductive Charging (DIC) systems for electric vehicles. The work implements and evaluates an MPC-based optimization approach that prioritizes vehicles with critical battery states, improving user satisfaction under resource scarcity.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Configuration](#configuration)
- [Defining Flows](#defining-vehicles-flows)
- [ChargingStations deployment](#chargingstations-deployment)
- [Running Simulations](#running-simulations)
- [Analysis](#analysis)

---

## Overview

Dynamic Inductive Charging (DIC) enables electric vehicles to charge wirelessly while driving on equipped road segments. However, when demand exceeds available power capacity, uncoordinated allocation leads to suboptimal resource utilization and user dissatisfaction. 

This framework implements a **Model Predictive Control (MPC)** strategy that:
- Dynamically allocates power based on vehicle urgency (battery state and remaining travel time)
- Optimizes satisfaction fairness by prioritizing critical vehicles
- Enables dynamic power rebalancing across charging infrastructure stripes
- Provides simulation and analysis tools using SUMO traffic simulator

### Key Features

- **MPC-based Power Allocation**: Convex quadratic programming formulation solved in real-time
- **Realistic Urban Scenario**: Istanbul Üsküdar topology with 10 DIC-equipped road segments
- **Flexible Traffic Modeling**: Configurable demand patterns, with configurable vehicle injection process
- **Performance Metrics**: User satisfaction indices, energy delivery, power utilization
- **Reproducible Research**: Automated batch simulations, data processing pipelines, and visualization tools

### Scientific Context

This work is part of ongoing research on sustainable mobility and intelligent transportation systems. 
The framework enables system-level analysis of DIC performance under various operational strategies, traffic conditions, and infrastructure configurations.

**Related Publication**: *[Paper title and venue to be added upon acceptance]*

---

## Installation

### Prerequisites

- **Python 3.8+** with packages: `numpy`, `pandas`, `cvxpy`, `lxml`, `pyarrow`
- **Custom SUMO Build**: This project requires a modified version of SUMO with enhanced charging station outputs. Check [SUMOvnc2026](https://github.com/lorenzo-ghiro/sumo/tree/vnc2026).
Follow the [official SUMO build instructions](https://sumo.dlr.de/docs/Developer/index.html#build_instructions) for your operating system.

## Configuration

## Defining Vehicles Flows

```bash
cd src
./genflows.sh
```
The shell script relies on [src/genFlows.py](src/genFlows.py) to generate [SUMO Flows](https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html#repeated_vehicles_flows).

### Flow Generation Arguments:
```
--vpm VPM              Lambda: vehicles per minute per lane
--vtype VTYPE          (optional) Default "soulEV65"
--begin BEGIN          Begin time as hour of day (e.g., 17 for 17:00)
--end END              End time as hour of day (e.g., 18 for 18:00)
--vutinterval INT      Deterministic interval in seconds for spawning VUT vehicles (default: 60)
--novut                Skip generation of VUT (Vehicles Under Test) flows
```

**VUT (Vehicles Under Test)** are special vehicles spawned deterministically at fixed intervals (default: every 60 seconds) that follow the longest routes (NLe→ExitSL and SRe→ExitNR). 
`genFlows.py` generates the deterministic VUT flows, while their behavior and configuration (initial SOC, desired SOC, etc.) are defined by `runner.py` through parameters like `--vutisocl` (VUT initial SOC level, default 1e-4 ≈ empty battery), making them ideal for testing extreme charging urgency scenarios.

The flow file naming convention is: `flow_{begin}_{end}_vpm{rate}_VUT{interval}.xml`
- VUT60: includes VUT vehicles every 60 seconds  
- VUT0: no VUT vehicles


## ChargingStations deployment

The [generate_cs.py](/src/generate_cs.py) script parse the provided net.xml file (`--net`), detects edges longer than `minedgelength` (default 5m) and deploys charging stations according to the desired policy. 
Currently supported policies:
- `fullrightmost`: fully covers only the rightmost lane of each road/edge
- `full_lane0_lane1`: fully covers the first 2 lanes of each road/edge

More policies can be defined/implemented in [generate_cs.py](/src/generate_cs.py)

`--nominalPower` defaults to `100kW` is the maximum power of a coil composing a stripe (stripe aka charging station).
`--powerbudget` defaults to `10MW` is the total power of budget that will be distributed to the various charging stations. The power distribution is performed here proportionally to the charging stations lengths.
At run-time the `runner.py` may re-allocate this `powerbudget` by re-setting the `totalPower` attribute of charging-stations.

Usage example:
```console
➜python generate_cs.py \                                         
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
Stripes (charging stations) belonging to the same edge are controlled by `runner.py` as a single stripe.
That's why in this example the user reads **20**` charginStations defined in cs.add.xml`
but then the table reports only 10 entries, this because all the reported edges in this example have 2 lanes.


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

- `--mpcInterval`: MPC optimization interval in seconds. If positive, enables MPC-based optimization at the specified interval. If negative, disables MPC and uses the absolute value to control how often vehicles are checked at runtime: at each interval, the system toggles the charging interface on/off for vehicles that have-not/have reached their desired SOC. 
  
  This workaround is necessary because, in SUMO, electric vehicles are always assumed to want to charge up to their full battery capacity. To implement more realistic behavior (e.g., stopping charging when a target SOC is reached), the architecture disables onboard charging by setting the `device.battery.maximumChargeRate` parameter to zero for vehicles that have reached their desired SOC, and re-enables it as needed. This allows fine-grained control over charging logic despite SUMO's default behavior.
- `--distrib`: SOC distribution as "U(init_min,init_max)-U(des_min,des_max)"
  - Current setup: U(0.1,0.49)-U(0.5,1.0) means initial SOC in [0.1, 0.49], desired SOC in [0.5, 1.0]
- `--vutisocl`: Initial SOC level for VUT vehicles (default: 1e-4, nearly empty)
- `--fromt`: Time when MPC control starts (format: HH:MM:SS). Before this time, system runs in warmup mode.
- `--begin/--end`: Simulation time window
- `--nogui`: Run without SUMO graphical interface (faster)

### Batch Simulations:
Generate all simulation commands for a given simulation seed: (requires [runmaker](https://github.com/veins/runmaker))

Example for seed=0
```bash
./printsim.sh 0 > runs
```
This outputs on a `runs` file the list of commands to execute 12 simulations (3 time periods × 2 VUT settings × 2 strategies):
- **Time periods**: 2-4h (λ=5 vpm), 11-13h (λ=12 vpm), 16-18h (λ=20 vpm)
- **VUT settings**: VUT60 (with VUT vehicles every 60s), VUT0 (no VUT vehicles)
- **Strategies**: OPT (mpcInterval=5), Benchmark (mpcInterval=-5)

Execute the commands (example):
```bash
time runmaker4.py -j 0 runs
```

Please, check and edit the head of [printsim.sh](/printsim.sh) to choose different simulations to run.

## Analysis

Further instructions in dedicated [analysis/README.md](/analysis/README.md) file.