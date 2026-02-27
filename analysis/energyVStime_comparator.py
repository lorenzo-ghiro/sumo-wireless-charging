"""
Compare energy charged over time between BENCH and OPT for selected vehicles.
Plots time series of cumulative energy charged for one VUT and one normal vehicle.
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path
import re

plt.rcParams.update({"text.usetex": True, "font.family": "sans-serif",
                     "font.sans-serif": ["Arial"], "axes.grid": True})


def extract_scenario_info(filepath):
    """
    Extract scenario info from filename: seed, time range, vpm, VUT%, distribution.
    Example: seed0_16_18_vpm20_VUT60_U(0.1,0.2)-U(1.0,1.0)_...
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

    parts = ['energyVStime']

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
        description="Compare energy charged evolution BENCH vs OPT")
    parser.add_argument("--opt", required=True,
                        help="OPT battery.out.parquet file")
    parser.add_argument("--bench", required=True,
                        help="BENCH battery.out.parquet file")
    parser.add_argument("--tripinfo", required=True,
                        help="tripinfo.out.parquet file")
    parser.add_argument("--fromt", required=True,
                        help="Analysis start time HH:MM:SS")
    parser.add_argument("--vutids", default="VUT_SRe_ExitNR.15,VUT_SRe_ExitNR.25,VUT_NLe_ExitSL.35",
                        help="Vehicle IDs to analyze: 'auto' or 'VUT_XXX,VUT_YYY,VUT_ZZZ'")
    parser.add_argument("--output", default="energy_vs_time_comparison.pdf",
                        help="Output PDF filename")
    return parser.parse_args()


def load_battery_data(filepath, vehicle_ids=None):
    """Load battery data with only necessary columns.

    Args:
        filepath: Path to parquet file
        vehicle_ids: Optional list of vehicle IDs to filter for

    Columns: timestep_time, vehicle_id, vehicle_energyCharged
    """
    # Columns to load
    columns_to_load = [
        'timestep_time',
        'vehicle_id',
        'vehicle_energyCharged'
    ]

    # If specific vehicle IDs provided, use parquet filter for efficiency
    if vehicle_ids is not None:
        df = pd.read_parquet(filepath, columns=columns_to_load, filters=[
                             ('vehicle_id', 'in', vehicle_ids)])
    else:
        df = pd.read_parquet(filepath, columns=columns_to_load)

    # Convert to numeric (should already be, but just in case)
    df['timestep_time'] = pd.to_numeric(df['timestep_time'], errors='coerce')
    df['vehicle_energyCharged'] = pd.to_numeric(
        df['vehicle_energyCharged'], errors='coerce')

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


def select_three_vuts_auto(tripinfo_df, battery_df, fromt_seconds):
    """
    Automatically select 3 VUT vehicles: first after fromt, fromt+10min, fromt+20min.

    Args:
        fromt_seconds: Analysis start time in seconds

    Returns:
        list: [vut_id1, vut_id2, vut_id3]
    """
    time_offsets = [0, 600, 1200]  # 0min, 10min, 20min in seconds
    selected_vuts = []

    for offset in time_offsets:
        target_time = fromt_seconds + offset

        # Filter for completed trips (have arrival_time) and departed after target_time
        completed = tripinfo_df[
            (tripinfo_df['tripinfo_arrival'].notna()) &
            (tripinfo_df['tripinfo_depart'] >= target_time)
        ].copy()

        if completed.empty:
            print(f"Warning: No completed trips found after fromt+{offset//60}min")
            continue

        # Find VUT vehicles (start with "VUT_")
        vut_vehicles = completed[completed['tripinfo_id'].str.startswith(
            'VUT_', na=False)]

        if vut_vehicles.empty:
            print(f"Warning: No VUT vehicles found after fromt+{offset//60}min")
            continue

        # Sort by depart_time and take the FIRST one
        vut_candidates = vut_vehicles.sort_values('tripinfo_depart')

        # Try to find a VUT with battery data
        found = False
        for idx in range(min(3, len(vut_candidates))):  # Try up to 3 candidates
            vut_id = vut_candidates.iloc[idx]['tripinfo_id']
            if vut_id in battery_df['vehicle_id'].values:
                selected_vuts.append(vut_id)
                found = True
                break

        if not found:
            print(f"Warning: No VUT with battery data found after fromt+{offset//60}min")

    if len(selected_vuts) < 3:
        raise ValueError(f"Could not find 3 VUTs with battery data. Found only {len(selected_vuts)}")

    return selected_vuts


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


def plot_three_vuts_comparison(vut_trajs_bench, vut_trajs_opt, vut_ids, output_file):
    """
    Plot energy charged over trip duration for 3 VUTs comparing BENCH vs OPT.
    All curves in a single subplot with normalized time (trip duration).

    Args:
        vut_trajs_bench: List of 3 DataFrames with time and cumulative_energy_kwh for BENCH
        vut_trajs_opt: List of 3 DataFrames with time and cumulative_energy_kwh for OPT
        vut_ids: List of 3 vehicle IDs
        output_file: Output PDF filename
    """
    fig, ax = plt.subplots(1, 1, figsize=(4.2, 2.3), constrained_layout=True)

    # Colors: 3 shades of blue for BENCH, 3 shades of orange for OPT
    bench_colors = ['#4A90E2', '#357ABD', '#2C5F8D']  # Light to dark blue
    opt_colors = ['#FFB347', '#FF8C42', '#FF6B35']    # Light to dark orange

    # Time formatter function: converts seconds to MM:SS format
    def format_time_mmss(x, pos=None):
        """Format seconds as MM:SS"""
        minutes = int(x // 60)
        seconds = int(x % 60)
        return f"{minutes}:{seconds:02d}"

    time_formatter = mticker.FuncFormatter(format_time_mmss)

    # Plot BENCH curves (no labels) - with circle markers
    for i, (vut_bench, color) in enumerate(zip(vut_trajs_bench, bench_colors)):
        ax.plot(vut_bench['time'], vut_bench['cumulative_energy_kwh'],
                color=color, linewidth=1.5, alpha=0.8, marker='o',
                markersize=1.5, markevery=80)

    # Plot OPT curves (no labels) - with square markers
    for i, (vut_opt, color) in enumerate(zip(vut_trajs_opt, opt_colors)):
        ax.plot(vut_opt['time'], vut_opt['cumulative_energy_kwh'],
                color=color, linewidth=1.5, alpha=0.8, marker='s',
                markersize=1.5, markevery=80)

    ax.set_xlabel('Trip Duration [MM:SS]', fontsize=10)
    ax.set_ylabel('Cumulative Energy [kWh]', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.tick_params(labelsize=9)
    ax.xaxis.set_major_formatter(time_formatter)

    # Create legend with only 2 entries: BENCH and OPT
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='#357ABD', linewidth=2,
               marker='o', markersize=3, label='BENCH'),
        Line2D([0], [0], color='#FF8C42', linewidth=2,
               marker='s', markersize=3, label='OPT')
    ]
    ax.legend(handles=legend_elements, loc='best', fontsize=9)

    # Save figure
    plt.savefig(output_file, format='pdf', bbox_inches='tight')
    print(f"\nSaved 3-VUT comparison plot to {output_file}")

    # Print summary statistics
    print("\n" + "="*70)
    print("SUMMARY STATISTICS - 3 VUTs")
    print("="*70)

    for i, (vut_bench, vut_opt, vut_id) in enumerate(zip(vut_trajs_bench, vut_trajs_opt, vut_ids)):
        bench_final = vut_bench['cumulative_energy_kwh'].iloc[-1]
        opt_final = vut_opt['cumulative_energy_kwh'].iloc[-1]
        diff = opt_final - bench_final

        print(f"\nVUT {i+1}: {vut_id}")
        print(f"  BENCH final energy: {bench_final:.3f} kWh")
        print(f"  OPT final energy:   {opt_final:.3f} kWh")
        print(f"  Difference:         {diff:+.3f} kWh")


def main():
    args = parse_args()

    # Auto-generate output filename if using default
    if args.output == "energy_vs_time_comparison.pdf":
        args.output = generate_output_filename(args.bench, args.opt)
        print(f"Auto-generated output filename: {args.output}")

    # Parse fromt to seconds
    fromt_parts = args.fromt.split(':')
    if len(fromt_parts) != 3:
        raise ValueError("--fromt must be in HH:MM:SS format")
    fromt_seconds = int(fromt_parts[0]) * 3600 + \
        int(fromt_parts[1]) * 60 + int(fromt_parts[2])
    print(f"Analysis start time (fromt): {args.fromt} ({fromt_seconds}s)")

    # ========================================================================
    # 3 VUT ANALYSIS: Compare 3 VUTs at fromt, fromt+10min, fromt+20min
    # ========================================================================
    print("\n" + "="*70)
    print("SELECTING 3 VUT VEHICLES")
    print("="*70)

    # Determine which vehicles to analyze
    if args.vutids.lower() == 'auto':
        print("\nAuto-selecting 3 VUTs (at fromt, fromt+10min, fromt+20min)...")
        print("Loading tripinfo data...")
        tripinfo = load_tripinfo_data(args.tripinfo)
        print("Loading battery data (all vehicles)...")
        battery_bench = load_battery_data(args.bench)
        battery_opt = load_battery_data(args.opt)

        vut_ids = select_three_vuts_auto(
            tripinfo, battery_bench, fromt_seconds)
        print(f"  Selected VUT 1 (fromt+0min):  {vut_ids[0]}")
        print(f"  Selected VUT 2 (fromt+10min): {vut_ids[1]}")
        print(f"  Selected VUT 3 (fromt+20min): {vut_ids[2]}")
    else:
        # Parse comma-separated IDs
        ids = args.vutids.split(',')
        if len(ids) != 3:
            raise ValueError(
                "--vutids must be 'auto' or three comma-separated VUT IDs")
        vut_ids = [vid.strip() for vid in ids]
        print(f"\nUsing user-specified vehicles:")
        for i, vid in enumerate(vut_ids, 1):
            print(f"  VUT {i}: {vid}")

        # Load battery data with filter for specific vehicles only
        print("\nLoading battery data (filtered for specified VUTs)...")
        battery_bench = load_battery_data(args.bench, vehicle_ids=vut_ids)
        battery_opt = load_battery_data(args.opt, vehicle_ids=vut_ids)

    # Extract trajectories for all 3 VUTs
    print("Extracting energy trajectories for 3 VUTs...")

    # Load tripinfo to get depart times for normalization
    print("Loading tripinfo data for depart times...")
    tripinfo = load_tripinfo_data(args.tripinfo)

    vut_trajs_bench = []
    vut_trajs_opt = []

    for vut_id in vut_ids:
        # Get depart_time for this vehicle
        vut_trip = tripinfo[tripinfo['tripinfo_id'] == vut_id]
        if vut_trip.empty:
            raise ValueError(f"No tripinfo found for VUT {vut_id}")
        depart_time = vut_trip.iloc[0]['tripinfo_depart']

        # Extract trajectories with normalized time (trip duration)
        vut_bench_traj = get_vehicle_energy_trajectory(
            battery_bench, vut_id, depart_time)
        vut_opt_traj = get_vehicle_energy_trajectory(
            battery_opt, vut_id, depart_time)

        if vut_bench_traj is None or vut_bench_traj.empty:
            raise ValueError(f"No battery data found for VUT {vut_id} in BENCH")
        if vut_opt_traj is None or vut_opt_traj.empty:
            raise ValueError(f"No battery data found for VUT {vut_id} in OPT")

        vut_trajs_bench.append(vut_bench_traj)
        vut_trajs_opt.append(vut_opt_traj)

        print(f"  {vut_id} - BENCH: {len(vut_bench_traj)} points, OPT: {len(vut_opt_traj)} points")

    # Create plot for 3 VUTs comparison
    print("\n" + "="*70)
    print("GENERATING 3-VUT COMPARISON PLOT")
    print("="*70)
    plot_three_vuts_comparison(
        vut_trajs_bench, vut_trajs_opt, vut_ids, args.output)


if __name__ == "__main__":
    main()
