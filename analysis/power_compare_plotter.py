"""
Power comparison plotter: creates a 3x2 grid comparing benchmark (MPCI=-5) vs optimized (MPCI=5)
for three time scenarios: 2-4h, 11-13h, 16-18h
"""

import argparse
from glob import glob
from datetime import datetime, time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

plt.rcParams.update({"text.usetex": True, "font.family": "sans-serif",
                     "font.sans-serif": ["Arial"], "axes.grid": True})

CS_NOMINAL_POWER_KW = 100.0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--folder", default="../results", help="Results folder")
    p.add_argument("--seed", default=0, type=int, help="Simulation seed")
    p.add_argument("--aggregation", default=20, type=int,
                   help="Aggregation window in seconds")
    p.add_argument("--vut", default=60, type=int,
                   choices=[0, 60], help="VUT interval")
    p.add_argument("--csxml", default="../src/cs.add.xml",
                   help="Charging stations XML file")
    p.add_argument("--output", default="power_comparison.pdf",
                   help="Output PDF filename")
    return p.parse_args()


def seconds_to_datetime_today(seconds):
    """Convert seconds since midnight to datetime object for today's date."""
    d = datetime.today().date()
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    return datetime.combine(d, time(h, m, s))


def get_total_charging_power_w(csxml, tol=1e-9):
    tree = ET.parse(csxml)
    root = tree.getroot()
    total_w, effs, missing = 0.0, [], []
    for cs in root.iter("chargingStation"):
        if cs.get("totalPower") is not None:
            total_w += float(cs.get("totalPower"))
        if cs.get("efficiency") is None:
            missing.append(cs.get("id", "<no-id>"))
        else:
            effs.append(float(cs.get("efficiency")))
    if missing:
        raise ValueError("Missing efficiency for: " + ", ".join(missing))
    if not effs:
        raise ValueError("No efficiency attribute found in csxml")
    e0 = effs[0]
    if any(abs(e - e0) > tol for e in effs[1:]):
        raise ValueError("Non-uniform efficiency values: %s" %
                         sorted(set(effs)))
    return total_w, e0


def process_battery(df, vehdf, aggr, efficiency):
    """Process battery data to aggregate by time bins."""
    # Create time bins for all data
    df['tbin'] = (df['time'] / aggr).astype(int)

    # Merge with vehicle attributes to get desired SOC
    df = df.merge(vehdf[['vid', 'des_soc']], on='vid', how='left')

    # Calculate energy gap: Egap = des_soc - soc [Wh]
    df['Egap'] = (df['des_soc'] - df['soc']).clip(lower=0)

    # Cap Egap to maximum feasible energy transfer
    DELTA_T = 0.25  # SUMO simulation timestep
    maxEnergyRequest_Wh = CS_NOMINAL_POWER_KW * 1000 * DELTA_T / 3600
    df['FeasibleEgap'] = df['Egap'].clip(upper=maxEnergyRequest_Wh)

    # Power request is only defined for vehicles on charging coils
    df['energyRequest'] = df['FeasibleEgap'] * efficiency
    df.loc[df['csid'].isna(), 'energyRequest'] = 0

    # Aggregate energyRequest by time bin
    energyRequest_by_bin = df.groupby(
        'tbin')['energyRequest'].sum().reset_index()

    # Aggregate energy charged by time bin
    energy_by_bin = df.groupby('tbin')['energyCharged'].sum().reset_index()

    # Create continuous time range
    tbin_min = df['tbin'].min()
    tbin_max = df['tbin'].max()
    all_bins = pd.DataFrame({'tbin': range(tbin_min, tbin_max + 1)})

    # Merge to ensure all time bins are present
    out = all_bins.merge(energy_by_bin, on='tbin', how='left').fillna(0)
    out = out.merge(energyRequest_by_bin, on='tbin', how='left').fillna(0)

    # Convert energy [Wh] to power [MW]
    out['powerCharged_MW'] = out['energyCharged'] * 3600 / aggr / 10**6
    out['powerRequested_MW'] = out['energyRequest'] * 3600 / aggr / 10**6

    # Convert time bins to datetime for plotting
    out['bintime'] = out['tbin'].apply(
        lambda x: seconds_to_datetime_today((x + 1) * aggr))
    return out


def load_scenario_data(folder, seed, begin, end, vut, mpcInterval, aggregation, efficiency, vehdf_cache):
    """Load and process data for a specific scenario."""
    # Pattern for battery files
    battery_pattern = "%s/seed_%d_%d_%d_vpm*VUT%d*mpcInterval_%d*battery*.parquet" % \
                      (folder, seed, begin, end, vut, mpcInterval)
    battery_files = glob(battery_pattern)

    if not battery_files:
        raise FileNotFoundError(f"No battery.out.parquet files found: {battery_pattern}")
    battery_file = battery_files[0]

    # Pattern for generated vehicles
    veh_pattern = "%s/seed_%d_%d_%d_vpm*VUT%d*mpcInterval_%d*generated_vehs.parquet" % \
                  (folder, seed, begin, end, vut, mpcInterval)
    veh_files = glob(veh_pattern)

    if not veh_files:
        raise FileNotFoundError(f"No generated_vehs.parquet file found: {veh_pattern}")
    veh_file = veh_files[0]

    # Check cache for vehdf
    cache_key = veh_file
    if cache_key in vehdf_cache:
        vehdf = vehdf_cache[cache_key]
    else:
        # Read generated vehicles data
        vehdf = pd.read_parquet(veh_file)
        for col in vehdf.columns:
            if 'id' not in col.lower():
                vehdf[col] = pd.to_numeric(vehdf[col], errors='coerce')
        vehdf_cache[cache_key] = vehdf

    # Read battery parquet file
    columns_to_read = [
        'timestep_time',
        'vehicle_actualBatteryCapacity',
        'vehicle_maximumBatteryCapacity',
        'vehicle_chargingStationId',
        'vehicle_energyCharged',
        'vehicle_id',
    ]

    df = pd.read_parquet(battery_file, columns=columns_to_read)

    # Rename columns
    df = df.rename(columns={
        'timestep_time': 'time',
        'vehicle_actualBatteryCapacity': 'soc',
        'vehicle_maximumBatteryCapacity': 'Bmax',
        'vehicle_chargingStationId': 'csid',
        'vehicle_energyCharged': 'energyCharged',
        'vehicle_id': 'vid',
    })

    # Force numeric types
    for col in df.columns:
        if col not in ['vid', 'csid']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Convert SUMO's string "NULL" to proper NaN
    df['csid'] = df['csid'].replace('NULL', np.nan)

    # Process battery data
    powdf = process_battery(df, vehdf, aggregation, efficiency)

    return powdf


def plot_scenario(ax, powdf, from_time_str, cap_mw, efficiency, title, show_ylabel=False, show_xlabel=False, lambd=0):
    """Plot a single scenario on the given axis."""
    # Filter by from_time
    from_time = pd.to_datetime(from_time_str).time()
    powdf_filtered = powdf[powdf.bintime.dt.time > from_time]

    # Plot data
    ax.step(powdf_filtered.bintime, powdf_filtered.powerRequested_MW, where="post",
            label=r"$P^r_{tot,t}$ [MW]", color="green", ls="-", marker="x", markersize=2, alpha=0.7)
    ax.step(powdf_filtered.bintime, powdf_filtered.powerCharged_MW, where="post",
            label=r"$P^d_{tot,t}$ [MW]", color="blue", ls="-", marker=".", markersize=2, alpha=0.7)

    ax.axhline(cap_mw * efficiency, ls="--",
               label=r"$P_{tot} \cdot \eta$", color="red")

    ax.set_xlim(powdf_filtered.bintime.min(), powdf_filtered.bintime.max())
    ax.set_ylim(0, 33.01)
    ax.xaxis.set_minor_locator(mdates.MinuteLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    if show_xlabel:
        ax.set_xlabel("Time")

    if show_ylabel:
        ax.set_ylabel("Power [MW]")

    ax.grid(True, which='both', alpha=0.4)
    ax.grid(True, which='minor', alpha=0.1)
    # ax.set_title(title, fontsize=10)

    # Calculate and annotate total energy distributed
    # total_energy_kwh = powdf_filtered['energyCharged'].sum() / 1e6  # Convert Wh to MWh
    ypos = 0.92 if "Low traffic" in lambd else 0.18
    ax.text(0.98, ypos, lambd,
            transform=ax.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Remove individual legend if present
    if ax.get_legend() is not None:
        ax.get_legend().remove()


def main():
    a = parse_args()

    # Get total charging power capacity
    cap_w, efficiency = get_total_charging_power_w(a.csxml)
    cap_mw = cap_w / 10**6

    # Define scenarios: (begin, end, from_time)
    scenarios = [
        (2, 4, "3:00", r"Low traffic ($\lambda = 5$ VPM)"),
        (11, 13, "12:00", r"Medium traffic ($\lambda = 12$ VPM)"),
        (16, 18, "17:00", r"Intense traffic ($\lambda = 20$ VPM)"),
    ]

    # Define MPCI values: benchmark and optimized
    mpci_values = [-5, 5]
    mpci_labels = ["Benchmark (MPCI=-5)", "Optimized (MPCI=5)"]

    # Create figure with 3 rows x 2 columns
    fig, axes = plt.subplots(3, 2, figsize=(
        10.5, 4.375), constrained_layout=True, gridspec_kw={'hspace': 0.13})

    # Cache for vehicle dataframes
    vehdf_cache = {}

    # Plot each scenario
    for row, (begin, end, from_time, lambd) in enumerate(scenarios):
        print(f"\nProcessing scenario: begin={begin}, end={end}, from_time={from_time}")

        for col, (mpci, mpci_label) in enumerate(zip(mpci_values, mpci_labels)):
            print(f"  MPCI={mpci}")

            # Load data
            powdf = load_scenario_data(
                a.folder, a.seed, begin, end, a.vut, mpci,
                a.aggregation, efficiency, vehdf_cache
            )

            # Create title (only for top row)
            title = mpci_label if row == 0 else ""

            # Show y-label only for left column
            show_ylabel = (col == 0)

            # Show x-label only for bottom row
            show_xlabel = (row == 2)

            # Plot
            plot_scenario(
                axes[row, col], powdf, from_time, cap_mw, efficiency,
                title, show_ylabel, show_xlabel, lambd
            )

    # Create a single legend for the entire figure
    legend_labels = [r"$P^r_{tot,t}$ [MW]",
                     r"$P^d_{tot,t}$ [MW]", r"$P_{tot} \cdot \eta$"]
    legend_handles = [
        Line2D([0], [0], color="green", ls="-",
               marker="x", markersize=4, alpha=0.7),
        Line2D([0], [0], color="blue", ls="-",
               marker=".", markersize=4, alpha=0.7),
        Line2D([0], [0], color="red", ls="--")
    ]

    fig.legend(legend_handles, legend_labels, loc='upper center', ncol=3,
               bbox_to_anchor=(0.52, 1.09), frameon=True, fontsize=11)

    # Save figure
    plt.savefig(a.output, format="pdf", bbox_inches="tight")
    print(f"\nSaved: {a.output}")


if __name__ == "__main__":
    main()
