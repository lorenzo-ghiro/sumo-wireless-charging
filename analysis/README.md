## Automatic XML 2 Parquet conversion

[Makefile] invokes the SUMO_TOOL `$(SUMO_TOOLS)/xml/xml2parquet.py` to convert all xml outputs under the specified folder (defaults `../results`) into parquet

```
make -j $(nproc)
```

## Power Analysis

[power_compare_plotter.py](power_compare_plotter.py) plots a 3x2 grid, with each cell displaying the Requested and Transferred Power over Time. 
3 traffic scenarios (low, medium, intense) x 2 power-management policies: *benchmark* (left), *optimized* (right)

```bash
python power_compare_plotter.py

Processing scenario: begin=2, end=4, from_time=3:00
  MPCI=-5
  MPCI=5

Processing scenario: begin=11, end=13, from_time=12:00
  MPCI=-5
  MPCI=5

Processing scenario: begin=16, end=18, from_time=17:00
  MPCI=-5
  MPCI=5

Saved: power_comparison.pdf
```


**Power Evolution Plots:**

[plot_energy_evolution.sh](plot_energy_evolution.sh) plots the evolution of the Charged Energy [kWh] over time for some selected vehicles.

```bash
./plot_energy_evolution.sh

[...]

==========================================
Done! Generated PDFs:
  - energyVStime_s0_2-4h_vpm5_VUT60.pdf
  - energyVStime_s0_11-13h_vpm12_VUT60.pdf
  - energyVStime_s0_16-18h_vpm20_VUT60.pdf
==========================================

```


## Satisfaction Analysis

### Processing Satisfaction Data:

Before plotting user satisfaction data, battery-output and other simulation output must be pre-processed.
[satisProcess.sh](satisProcess.sh) automates this required pre-processing that is actually implemented by [satis.py](satis.py)


```bash
cd analysis
./satisProcess.sh
```

### Generating Plots:

**Satisfaction Distribution (ECDF or PDF):**
```bash
./distrib_plotter_satis.sh
```

### Output Files:

Simulation outputs (in `results/`):
- `*_battery.out.parquet`: Battery state evolution (timestep, vid, SOC, charging station, energy consumed)
- `*_tripinfo.out.parquet`: Trip information (vid, depart, arrival, route, duration)
- `*_generated_vehs.parquet`: Vehicle parameters (vid, initial_soc, des_soc, exit_soc, Bmax)
- `*_chargingstations.parquet`: Charging station activity logs

Analysis outputs (in `analysis/parquets/`):
- `satisfaction_moments_*.parquet`: Satisfaction metrics at departure and arrival for each vehicle
