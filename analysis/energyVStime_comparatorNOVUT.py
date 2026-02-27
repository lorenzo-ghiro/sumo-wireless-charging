"""
Compare energy charged over time between BENCH and OPT for NOVUT scenario.
Plots time series of cumulative energy charged for 3 top-scorers and 3 worst-scorers.
Top-scorers: vehicles that gained the most energy with OPT vs BENCH
Worst-scorers: vehicles that lost the most energy with OPT vs BENCH
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path
from tabulate import tabulate
import re

plt.rcParams.update({"text.usetex": True, "font.family": "sans-serif",
                     "font.sans-serif": ["Arial"], "axes.grid": True})


def extract_scenario_info(filepath):
    """
    Extract scenario info from filename: seed, time range, vpm, distribution.
    Example: seed0_16_18_vpm20_VUT0_U(0.1,0.2)-U(1.0,1.0)_...
    Returns: dict with extracted info
    """
    filename = Path(filepath).name

    info = {}

    # Extract seed
    seed_match = re.search(r'seed(\d+)', filename)
    if seed_match:
        info['seed'] = f"s{seed_match.group(1)}"

    # Extract time range
    time_match = re.search(r'_(\d+)_(\d+)_', filename)
    if time_match:
        info['time'] = f"{time_match.group(1)}-{time_match.group(2)}h"

    # Extract vpm
    vpm_match = re.search(r'vpm(\d+)', filename)
    if vpm_match:
        info['vpm'] = f"vpm{vpm_match.group(1)}"

    # Extract VUT percentage
    vut_match = re.search(r'VUT(\d+)', filename)
    if vut_match:
        info['vut'] = f"VUT{vut_match.group(1)}"

    # Extract distribution (simplified)
    dist_match = re.search(r'U\([^)]+\)-U\([^)]+\)', filename)
    if dist_match:
        # Simplify the distribution notation
        dist_str = dist_match.group(0)
        info['dist'] = dist_str.replace(
            '(', '').replace(')', '').replace(',', '_')

    return info


def generate_output_filename(bench_file, opt_file):
    """
    Generate output filename based on input files.
    """
    info = extract_scenario_info(bench_file)

    parts = ['energyVStime_NOVUT']

    if 'seed' in info:
        parts.append(info['seed'])
    if 'time' in info:
        parts.append(info['time'])
    if 'vpm' in info:
        parts.append(info['vpm'])
    if 'vut' in info:
        parts.append(info['vut'])

    filename = '_'.join(parts) + '.pdf'
    return filename


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare energy charged evolution BENCH vs OPT for NOVUT scenario")
    parser.add_argument("--opt", required=True,
                        help="OPT battery.out.parquet file")
    parser.add_argument("--bench", required=True,
                        help="BENCH battery.out.parquet file")
    parser.add_argument("--tripinfo", required=True,
                        help="tripinfo.out.parquet file")
    parser.add_argument("--genveh", required=True,
                        help="Generated vehicle data parquet file (gen_vehdata...)")
    parser.add_argument("--fromt", required=True,
                        help="Analysis start time HH:MM:SS")
    parser.add_argument("--output", default="energy_vs_time_comparison_NOVUT.pdf",
                        help="Output PDF filename")
    return parser.parse_args()


def load_battery_data(filepath):
    """Load battery data with only necessary columns.

    Columns: timestep_time, vehicle_id, vehicle_energyCharged, 
             vehicle_actualBatteryCapacity, vehicle_maximumBatteryCapacity
    """
    # Load only the columns we need
    columns_to_load = [
        'timestep_time',
        'vehicle_id',
        'vehicle_energyCharged',
        'vehicle_actualBatteryCapacity',
        'vehicle_maximumBatteryCapacity'
    ]

    df = pd.read_parquet(filepath, columns=columns_to_load)

    # Convert to numeric (should already be, but just in case)
    df['timestep_time'] = pd.to_numeric(df['timestep_time'], errors='coerce')
    df['vehicle_energyCharged'] = pd.to_numeric(
        df['vehicle_energyCharged'], errors='coerce')
    df['vehicle_actualBatteryCapacity'] = pd.to_numeric(
        df['vehicle_actualBatteryCapacity'], errors='coerce')

    return df


def load_tripinfo_data(filepath):
    """Load tripinfo data with only necessary columns.

    Columns: tripinfo_id, tripinfo_depart, tripinfo_arrival
    """
    # Load only the columns we need
    columns_to_load = ['tripinfo_id', 'tripinfo_depart', 'tripinfo_arrival']

    df = pd.read_parquet(filepath, columns=columns_to_load)

    # Convert to numeric (should already be, but just in case)
    df['tripinfo_depart'] = pd.to_numeric(
        df['tripinfo_depart'], errors='coerce')
    df['tripinfo_arrival'] = pd.to_numeric(
        df['tripinfo_arrival'], errors='coerce')

    return df


def load_genveh_data(filepath):
    """Load generated vehicle data (initial conditions).

    Expected columns: vid, initial_soc, des_soc, Bmax, etc.
    """
    df = pd.read_parquet(filepath)

    # Check if 'vid' column exists, otherwise try common alternatives
    if 'vid' not in df.columns:
        vid_cols = ['vehicle_id', 'id']
        vid_col = None
        for col in vid_cols:
            if col in df.columns:
                vid_col = col
                break

        if vid_col is None:
            raise ValueError(f"Could not find vehicle ID column in {filepath}. Columns: {df.columns.tolist()}")

        # Rename to standard 'vid'
        df = df.rename(columns={vid_col: 'vid'})

    return df


def calculate_cumulative_energy_final(battery_df):
    """
    Calculate final cumulative energy for each vehicle.

    Returns:
        DataFrame with columns: vehicle_id, final_energy_kwh
    """
    # Group by vehicle and calculate cumulative energy
    result = battery_df.groupby('vehicle_id').agg({
        'vehicle_energyCharged': 'sum'
    }).reset_index()

    # Convert to kWh
    result['final_energy_kwh'] = result['vehicle_energyCharged'] / 1000.0

    return result[['vehicle_id', 'final_energy_kwh']]


def find_top_and_worst_scorers(bench_final, opt_final, n=3):
    """
    Find top N and worst N scorers by comparing OPT vs BENCH.

    Args:
        bench_final: DataFrame with vehicle_id, final_energy_kwh for BENCH
        opt_final: DataFrame with vehicle_id, final_energy_kwh for OPT
        n: Number of top/worst scorers to find

    Returns:
        tuple: (top_scorer_vids, worst_scorer_vids)
    """
    # Merge on vehicle ID
    merged = pd.merge(bench_final, opt_final, on='vehicle_id',
                      suffixes=('_bench', '_opt'))

    # Calculate difference: OPT - BENCH
    merged['energy_diff'] = merged['final_energy_kwh_opt'] - \
        merged['final_energy_kwh_bench']

    # Sort by difference
    merged_sorted = merged.sort_values('energy_diff', ascending=False)

    # Top scorers: highest positive difference
    top_scorers = merged_sorted.head(n)

    # Worst scorers: highest negative difference (i.e., lowest values)
    worst_scorers = merged_sorted.tail(n)

    print("\n" + "="*70)
    print("TOP SCORERS (gained most energy with OPT)")
    print("="*70)
    for idx, row in top_scorers.iterrows():
        print(f"  {row['vehicle_id']}: BENCH={row['final_energy_kwh_bench']:.3f} kWh, "
              f"OPT={row['final_energy_kwh_opt']:.3f} kWh, "
              f"Δ={row['energy_diff']:+.3f} kWh")

    print("\n" + "="*70)
    print("WORST SCORERS (lost most energy with OPT)")
    print("="*70)
    for idx, row in worst_scorers.iterrows():
        print(f"  {row['vehicle_id']}: BENCH={row['final_energy_kwh_bench']:.3f} kWh, "
              f"OPT={row['final_energy_kwh_opt']:.3f} kWh, "
              f"Δ={row['energy_diff']:+.3f} kWh")

    return top_scorers['vehicle_id'].tolist(), worst_scorers['vehicle_id'].tolist()


def get_vehicle_energy_trajectory(battery_df, vid, depart_time=None):
    """
    Extract energy charged trajectory for a specific vehicle.

    Args:
        battery_df: Battery dataframe
        vid: Vehicle ID
        depart_time: If provided, normalizes time to trip duration (time - depart_time)

    Returns:
        DataFrame with columns: time, cumulative_energy_kwh
    """
    veh_data = battery_df[battery_df['vehicle_id'] == vid].copy()

    if veh_data.empty:
        return None

    # Sort by time
    veh_data = veh_data.sort_values('timestep_time')

    # Normalize time to trip duration if depart_time provided
    if depart_time is not None:
        veh_data['time'] = veh_data['timestep_time'] - depart_time
    else:
        veh_data['time'] = veh_data['timestep_time']

    # Calculate cumulative energy [kWh]
    veh_data['cumulative_energy_kwh'] = veh_data['vehicle_energyCharged'].cumsum() / \
        1000.0

    return veh_data[['time', 'cumulative_energy_kwh']]


def plot_six_vehicles_comparison(top_trajs_bench, top_trajs_opt, worst_trajs_bench, worst_trajs_opt,
                                 top_vids, worst_vids, top_gaps, worst_gaps, output_file):
    """
    Plot energy charged over trip duration for 6 vehicles (3 top + 3 worst) comparing BENCH vs OPT.

    Args:
        top_trajs_bench: List of 3 DataFrames for top scorers BENCH
        top_trajs_opt: List of 3 DataFrames for top scorers OPT
        worst_trajs_bench: List of 3 DataFrames for worst scorers BENCH
        worst_trajs_opt: List of 3 DataFrames for worst scorers OPT
        top_vids: List of 3 top scorer vehicle IDs
        worst_vids: List of 3 worst scorer vehicle IDs
        top_gaps: List of 3 initial GAP values (normalized) for top scorers
        worst_gaps: List of 3 initial GAP values (normalized) for worst scorers
        output_file: Output PDF filename
    """
    fig, ax = plt.subplots(1, 1, figsize=(4.2, 2.3), constrained_layout=True)

    # Colors for top-scorers (first 3): orange for OPT, blue for BENCH
    opt_top_colors = ['#FF8C42', '#FFA04D', '#FFB347']
    bench_top_colors = ['#4A90E2', '#5DA3F0', '#70B6FF']

    # Colors for worst-scorers (last 3): green for OPT, purple for BENCH
    opt_worst_colors = ['#66BB6A', '#81C784', '#A5D6A7']
    bench_worst_colors = ['#AB47BC', '#BA68C8', '#CE93D8']

    # Combine colors
    opt_colors = opt_top_colors + opt_worst_colors
    bench_colors = bench_top_colors + bench_worst_colors

    # Markers: one per vehicle (same marker for OPT and BENCH of same vehicle)
    markers = ['o', 's', '^', 'D', 'v', 'p']

    # Combine all vehicle IDs and gaps in order (top scorers first, then worst scorers)
    all_vids = top_vids + worst_vids
    all_gaps = top_gaps + worst_gaps

    # Time formatter function: converts seconds to MM:SS format
    def format_time_mmss(x, pos=None):
        """Format seconds as MM:SS"""
        minutes = int(x // 60)
        seconds = int(x % 60)
        return f"{minutes}:{seconds:02d}"

    time_formatter = mticker.FuncFormatter(format_time_mmss)

    # Create labels with LaTeX subscripts
    def create_label(index, scenario):
        """Create label with LaTeX subscripts: oHD_n, bHD_n, oLD_n, bLD_n"""
        if index < 3:
            # High Demand (top scorer)
            label_type = "HD"
            n = index + 1
        else:
            # Low Demand (worst scorer)
            label_type = "LD"
            n = index - 2  # 3->1, 4->2, 5->3

        # Format: oHD_1, bHD_1, oLD_1, bLD_1
        scenario_prefix = "o" if scenario.upper() == "OPT" else "b"
        return f"{scenario_prefix}{label_type}$_{n}$"

    # Plot all BENCH curves first (so they appear in background)
    for i in range(len(all_vids)):
        if i < 3:  # Top scorer
            traj = top_trajs_bench[i]
        else:  # Worst scorer
            traj = worst_trajs_bench[i - 3]

        label = create_label(i, "BENCH")
        ax.plot(traj['time'], traj['cumulative_energy_kwh'],
                color=bench_colors[i], linewidth=1.5, alpha=0.7,
                marker=markers[i], markersize=1.5, markevery=80,
                label=label)

    # Plot all OPT curves (on top)
    for i in range(len(all_vids)):
        if i < 3:  # Top scorer
            traj = top_trajs_opt[i]
        else:  # Worst scorer
            traj = worst_trajs_opt[i - 3]

        label = create_label(i, "OPT")
        ax.plot(traj['time'], traj['cumulative_energy_kwh'],
                color=opt_colors[i], linewidth=1.5, alpha=0.85,
                marker=markers[i], markersize=1.5, markevery=80,
                label=label)

    ax.set_xlabel('Trip Duration [MM:SS]', fontsize=10)
    ax.set_ylabel('Cumulative Energy [kWh]', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)
    ax.xaxis.set_major_formatter(time_formatter)

    # Create annotation text with GAP values
    gap_text = ""
    for i in range(len(all_vids)):
        if i < 3:
            label_type = "HD"
            n = i + 1
        else:
            label_type = "LD"
            n = i - 2
        gap_text += f"{label_type}$_{n}$: GAP$_0$ = {all_gaps[i]:.2f}\n"

    # Remove trailing newline
    gap_text = gap_text.rstrip('\n')

    # Add annotation to plot (top-center)
    ax.text(0.5, 0.98, gap_text, transform=ax.transAxes,
            verticalalignment='top', horizontalalignment='center',
            fontsize=7, bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # Create legend with all vehicle curves (fixed in upper left)
    ax.legend(loc='upper left', fontsize=7, ncol=2)

    # Save figure
    plt.savefig(output_file, format='pdf', bbox_inches='tight')
    print(f"\nSaved 6-vehicle comparison plot to {output_file}")


def print_vehicle_initial_conditions_table(vids, genveh_df, tripinfo_df, battery_bench_df, battery_opt_df):
    """
    Print initial conditions and results for selected vehicles in a table format.

    Args:
        vids: List of vehicle IDs (first 3 are top scorers, last 3 are worst scorers)
        genveh_df: Generated vehicle data DataFrame
        tripinfo_df: Tripinfo DataFrame
        battery_bench_df: Battery DataFrame for BENCH
        battery_opt_df: Battery DataFrame for OPT
    """
    print("\n" + "="*100)
    print("INITIAL CONDITIONS AND RESULTS FOR SELECTED VEHICLES")
    print("="*100)

    table_data = []

    for i, vid in enumerate(vids):
        row = {'Vehicle': vid}

        # Determine if top or worst scorer
        if i < 3:
            row['Type'] = 'Top'
        else:
            row['Type'] = 'Worst'

        # Get data from genveh
        veh_gen = genveh_df[genveh_df['vid'] == vid]
        veh_trip = tripinfo_df[tripinfo_df['tripinfo_id'] == vid]

        if veh_gen.empty:
            print(f"\nWarning: {vid}: No generation data found")
            continue

        veh_gen = veh_gen.iloc[0]

        # Get battery capacity (Bmax in genveh data)
        battery_capacity = None
        for cap_col in ['Bmax', 'battery_capacity', 'capacity', 'batteryCapacity', 'maximumBatteryCapacity']:
            if cap_col in veh_gen.index and pd.notna(veh_gen[cap_col]):
                battery_capacity = float(veh_gen[cap_col])
                break

        # If still not found, try battery_df
        if battery_capacity is None:
            veh_battery = battery_opt_df[battery_opt_df['vehicle_id'] == vid]
            if not veh_battery.empty:
                cap_values = veh_battery['vehicle_maximumBatteryCapacity'].dropna(
                )
                if not cap_values.empty:
                    battery_capacity = float(cap_values.iloc[0])

        # Get trip info
        if not veh_trip.empty:
            veh_trip_data = veh_trip.iloc[0]
            depart_time = veh_trip_data['tripinfo_depart']

            # Format depart time
            hours = int(depart_time // 3600)
            minutes = int((depart_time % 3600) // 60)
            seconds = int(depart_time % 60)
            row['Depart'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Format arrival time
            if pd.notna(veh_trip_data['tripinfo_arrival']):
                arrival_time = veh_trip_data['tripinfo_arrival']
                hours_arr = int(arrival_time // 3600)
                minutes_arr = int((arrival_time % 3600) // 60)
                seconds_arr = int(arrival_time % 60)
                row['Arrival'] = f"{hours_arr:02d}:{minutes_arr:02d}:{seconds_arr:02d}"

                # Format trip duration
                trip_duration = arrival_time - depart_time
                duration_min = int(trip_duration // 60)
                duration_sec = int(trip_duration % 60)
                row['Duration'] = f"{duration_min}:{duration_sec:02d}"
            else:
                row['Arrival'] = 'N/A'
                row['Duration'] = 'N/A'
        else:
            row['Depart'] = 'N/A'
            row['Arrival'] = 'N/A'
            row['Duration'] = 'N/A'

        # Get initial SOC (normalized)
        initial_soc = None
        for soc_col in ['initial_soc', 'initialSOC', 'soc', 'b_init']:
            if soc_col in veh_gen.index and pd.notna(veh_gen[soc_col]):
                initial_soc = float(veh_gen[soc_col])
                break

        if initial_soc is not None and battery_capacity is not None and battery_capacity > 0:
            row['Init_SOC'] = f"{initial_soc / battery_capacity:.4f}"
        else:
            row['Init_SOC'] = 'N/A'

        # Get desired SOC (normalized)
        desired_soc = None
        for des_col in ['des_soc', 'b_des', 'desiredSOC', 'desired_soc']:
            if des_col in veh_gen.index and pd.notna(veh_gen[des_col]):
                desired_soc = float(veh_gen[des_col])
                break

        if desired_soc is not None and battery_capacity is not None and battery_capacity > 0:
            row['Des_SOC'] = f"{desired_soc / battery_capacity:.4f}"
        else:
            row['Des_SOC'] = 'N/A'

        # Calculate initial GAP (desired_soc - initial_soc, normalized)
        if initial_soc is not None and desired_soc is not None and battery_capacity is not None and battery_capacity > 0:
            gap_initial = desired_soc - initial_soc
            row['GAP_initial'] = f"{gap_initial / battery_capacity:.4f}"
        else:
            row['GAP_initial'] = 'N/A'

        # Get final SOC for BENCH and OPT
        veh_battery_bench = battery_bench_df[battery_bench_df['vehicle_id'] == vid]
        veh_battery_opt = battery_opt_df[battery_opt_df['vehicle_id'] == vid]

        # Calculate exit GAP for BENCH (desired_soc - final_soc, normalized)
        if not veh_battery_bench.empty and desired_soc is not None and battery_capacity is not None and battery_capacity > 0:
            # Get last actualBatteryCapacity (final SOC)
            final_soc_bench = veh_battery_bench.iloc[-1]['vehicle_actualBatteryCapacity']
            gap_bench = desired_soc - final_soc_bench
            row['GAP_BENCH_exit'] = f"{gap_bench / battery_capacity:.4f}"
        else:
            row['GAP_BENCH_exit'] = 'N/A'

        # Calculate exit GAP for OPT (desired_soc - final_soc, normalized)
        if not veh_battery_opt.empty and desired_soc is not None and battery_capacity is not None and battery_capacity > 0:
            # Get last actualBatteryCapacity (final SOC)
            final_soc_opt = veh_battery_opt.iloc[-1]['vehicle_actualBatteryCapacity']
            gap_opt = desired_soc - final_soc_opt
            row['GAP_OPT_exit'] = f"{gap_opt / battery_capacity:.4f}"
        else:
            row['GAP_OPT_exit'] = 'N/A'

        table_data.append(row)

    # Print table using dict keys as headers
    print(tabulate(table_data, headers='keys', tablefmt='grid'))


def main():
    args = parse_args()

    # Auto-generate output filename if using default
    if args.output == "energy_vs_time_comparison_NOVUT.pdf":
        args.output = generate_output_filename(args.bench, args.opt)
        print(f"Auto-generated output filename: {args.output}")

    # Parse fromt to seconds
    fromt_parts = args.fromt.split(':')
    if len(fromt_parts) != 3:
        raise ValueError("--fromt must be in HH:MM:SS format")
    fromt_seconds = int(fromt_parts[0]) * 3600 + \
        int(fromt_parts[1]) * 60 + int(fromt_parts[2])
    print(f"Analysis start time (fromt): {args.fromt} ({fromt_seconds}s)")

    # Load data
    print("\n" + "="*70)
    print("LOADING DATA")
    print("="*70)

    print("Loading BENCH battery data...")
    battery_bench = load_battery_data(args.bench)
    print(f"  Loaded {len(battery_bench)} records, {battery_bench['vehicle_id'].nunique()} vehicles")

    print("Loading OPT battery data...")
    battery_opt = load_battery_data(args.opt)
    print(f"  Loaded {len(battery_opt)} records, {battery_opt['vehicle_id'].nunique()} vehicles")

    print("Loading tripinfo data...")
    tripinfo = load_tripinfo_data(args.tripinfo)
    print(f"  Loaded {len(tripinfo)} trip records")

    print("Loading generated vehicle data...")
    genveh = load_genveh_data(args.genveh)
    print(f"  Loaded {len(genveh)} vehicle generation records")

    # Filter out vehicles born before fromt
    print("\n" + "="*70)
    print("FILTERING VEHICLES")
    print("="*70)

    # Get vehicles that departed at or after fromt
    vehicles_after_fromt = tripinfo[tripinfo['tripinfo_depart']
                                    >= fromt_seconds]['tripinfo_id'].unique()
    print(f"Vehicles departed at or after fromt: {len(vehicles_after_fromt)}")

    # Filter battery data
    battery_bench_filtered = battery_bench[battery_bench['vehicle_id'].isin(
        vehicles_after_fromt)]
    battery_opt_filtered = battery_opt[battery_opt['vehicle_id'].isin(
        vehicles_after_fromt)]

    print(f"  BENCH: {battery_bench_filtered['vehicle_id'].nunique()} vehicles after filtering")
    print(f"  OPT: {battery_opt_filtered['vehicle_id'].nunique()} vehicles after filtering")

    # Calculate final cumulative energy for each vehicle
    print("\n" + "="*70)
    print("CALCULATING CUMULATIVE ENERGY")
    print("="*70)

    bench_final = calculate_cumulative_energy_final(battery_bench_filtered)
    opt_final = calculate_cumulative_energy_final(battery_opt_filtered)

    print(f"  BENCH: Calculated final energy for {len(bench_final)} vehicles")
    print(f"  OPT: Calculated final energy for {len(opt_final)} vehicles")

    # Find top and worst scorers
    print("\n" + "="*70)
    print("FINDING TOP AND WORST SCORERS")
    print("="*70)

    top_vids, worst_vids = find_top_and_worst_scorers(
        bench_final, opt_final, n=3)

    # Extract trajectories for all 6 vehicles
    print("\n" + "="*70)
    print("EXTRACTING ENERGY TRAJECTORIES")
    print("="*70)

    all_vids = top_vids + worst_vids

    top_trajs_bench = []
    top_trajs_opt = []
    worst_trajs_bench = []
    worst_trajs_opt = []

    # Extract trajectories for top scorers
    print("\nTop scorers:")
    for vid in top_vids:
        # Get depart_time for this vehicle
        veh_trip = tripinfo[tripinfo['tripinfo_id'] == vid]
        if veh_trip.empty:
            raise ValueError(f"No tripinfo found for vehicle {vid}")
        depart_time = veh_trip.iloc[0]['tripinfo_depart']

        # Extract trajectories with normalized time (trip duration)
        traj_bench = get_vehicle_energy_trajectory(
            battery_bench, vid, depart_time)
        traj_opt = get_vehicle_energy_trajectory(battery_opt, vid, depart_time)

        if traj_bench is None or traj_bench.empty:
            raise ValueError(f"No battery data found for vehicle {vid} in BENCH")
        if traj_opt is None or traj_opt.empty:
            raise ValueError(f"No battery data found for vehicle {vid} in OPT")

        top_trajs_bench.append(traj_bench)
        top_trajs_opt.append(traj_opt)

        print(f"  {vid} - BENCH: {len(traj_bench)} points, OPT: {len(traj_opt)} points")

    # Extract trajectories for worst scorers
    print("\nWorst scorers:")
    for vid in worst_vids:
        # Get depart_time for this vehicle
        veh_trip = tripinfo[tripinfo['tripinfo_id'] == vid]
        if veh_trip.empty:
            raise ValueError(f"No tripinfo found for vehicle {vid}")
        depart_time = veh_trip.iloc[0]['tripinfo_depart']

        # Extract trajectories with normalized time (trip duration)
        traj_bench = get_vehicle_energy_trajectory(
            battery_bench, vid, depart_time)
        traj_opt = get_vehicle_energy_trajectory(battery_opt, vid, depart_time)

        if traj_bench is None or traj_bench.empty:
            raise ValueError(f"No battery data found for vehicle {vid} in BENCH")
        if traj_opt is None or traj_opt.empty:
            raise ValueError(f"No battery data found for vehicle {vid} in OPT")

        worst_trajs_bench.append(traj_bench)
        worst_trajs_opt.append(traj_opt)

        print(f"  {vid} - BENCH: {len(traj_bench)} points, OPT: {len(traj_opt)} points")

    # Print initial conditions for all 6 vehicles in table format
    print_vehicle_initial_conditions_table(
        all_vids, genveh, tripinfo, battery_bench, battery_opt)

    # Extract initial GAP values for plotting
    print("\nExtracting initial GAP values for plot labels...")
    top_gaps = []
    worst_gaps = []

    for vid in top_vids:
        veh_gen = genveh[genveh['vid'] == vid].iloc[0]
        # Get battery capacity
        battery_capacity = None
        for cap_col in ['Bmax', 'battery_capacity', 'capacity']:
            if cap_col in veh_gen.index and pd.notna(veh_gen[cap_col]):
                battery_capacity = float(veh_gen[cap_col])
                break
        # Get initial and desired SOC
        initial_soc = None
        for soc_col in ['initial_soc', 'initialSOC', 'soc']:
            if soc_col in veh_gen.index and pd.notna(veh_gen[soc_col]):
                initial_soc = float(veh_gen[soc_col])
                break
        desired_soc = None
        for des_col in ['des_soc', 'b_des', 'desiredSOC']:
            if des_col in veh_gen.index and pd.notna(veh_gen[des_col]):
                desired_soc = float(veh_gen[des_col])
                break
        # Calculate normalized gap
        if initial_soc is not None and desired_soc is not None and battery_capacity is not None:
            gap_normalized = (desired_soc - initial_soc) / battery_capacity
            top_gaps.append(gap_normalized)
        else:
            top_gaps.append(0.0)

    for vid in worst_vids:
        veh_gen = genveh[genveh['vid'] == vid].iloc[0]
        # Get battery capacity
        battery_capacity = None
        for cap_col in ['Bmax', 'battery_capacity', 'capacity']:
            if cap_col in veh_gen.index and pd.notna(veh_gen[cap_col]):
                battery_capacity = float(veh_gen[cap_col])
                break
        # Get initial and desired SOC
        initial_soc = None
        for soc_col in ['initial_soc', 'initialSOC', 'soc']:
            if soc_col in veh_gen.index and pd.notna(veh_gen[soc_col]):
                initial_soc = float(veh_gen[soc_col])
                break
        desired_soc = None
        for des_col in ['des_soc', 'b_des', 'desiredSOC']:
            if des_col in veh_gen.index and pd.notna(veh_gen[des_col]):
                desired_soc = float(veh_gen[des_col])
                break
        # Calculate normalized gap
        if initial_soc is not None and desired_soc is not None and battery_capacity is not None:
            gap_normalized = (desired_soc - initial_soc) / battery_capacity
            worst_gaps.append(gap_normalized)
        else:
            worst_gaps.append(0.0)

    # Create plot
    print("\n" + "="*70)
    print("GENERATING 6-VEHICLE COMPARISON PLOT")
    print("="*70)
    plot_six_vehicles_comparison(top_trajs_bench, top_trajs_opt, worst_trajs_bench, worst_trajs_opt,
                                 top_vids, worst_vids, top_gaps, worst_gaps, args.output)


if __name__ == "__main__":
    main()
