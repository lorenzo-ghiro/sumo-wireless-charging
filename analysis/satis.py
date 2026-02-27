import argparse
from datetime import datetime, time
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from tqdm import tqdm


# Constants
CS_NOMINAL_POWER_KW = 100.0  # kW - nominal power per coil
VEHICLE_CHARGING_POWER_KW = 150.0  # kW - vehicle charging capacity (P_on)
DELTA_T = 0.25  # seconds - SUMO simulation time step


def parse_args():
    p = argparse.ArgumentParser(
        description="Analyze user satisfaction from simulation results")
    p.add_argument("--folder", required=True, help="Path to results folder")
    p.add_argument("--seed", required=True, type=int, help="Simulation seed")
    p.add_argument("--aggregation", default=60, type=int,
                   help="Aggregation interval in seconds")
    p.add_argument("--begin", required=True, type=int,
                   help="Start time in seconds")
    p.add_argument("--end", required=True, type=int,
                   help="End time in seconds")
    p.add_argument("--fromt", required=True,
                   help="Time period identifier (e.g., '2_4_vpm5')")
    p.add_argument("--mpcInterval", required=True, type=int,
                   help="MPC interval used in simulation")
    p.add_argument("--vut", required=True, type=int,
                   choices=[0, 60], help="VUT interval: 60 for withVUT, 0 for noVUT")
    p.add_argument("--nickname", default="", help="nickname for output files")
    return p.parse_args()


def seconds_to_datetime_today(seconds):
    """Convert seconds since midnight to datetime object for today's date."""
    d = datetime.today().date()
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    return datetime.combine(d, time(h, m, s))


def load_data(folder, seed, begin, end, mpcInterval, vut):
    """Load required parquet files for satisfaction analysis.

    Parameters:
    - vut: int (0 or 60) - VUT interval to identify which files to load

    Returns:
    - generated_vehs: DataFrame
    - tripinfo: DataFrame
    - battery: DataFrame
    - with_vut: bool - True if scenario has VUT (VUT60), False if no VUT (VUT0)
    """
    from glob import glob

    # Find files using glob pattern with begin/end hours and VUT specification
    generated_vehs_file = glob(f"{folder}/seed_{seed}_{begin}_{end}_vpm*VUT{vut}*mpcInterval_{mpcInterval}*generated_vehs.parquet")[0]
    tripinfo_file = glob(f"{folder}/seed_{seed}_{begin}_{end}_vpm*VUT{vut}*mpcInterval_{mpcInterval}*tripinfo.out.parquet")[0]
    battery_file = glob(f"{folder}/seed_{seed}_{begin}_{end}_vpm*VUT{vut}*mpcInterval_{mpcInterval}*battery.out.parquet")[0]

    # Detect scenario: VUT60 means with VUT, VUT0 means no VUT
    with_vut = vut == 60
    scenario_type = "withVUT" if with_vut else "noVUT"
    print(f"Detected scenario: {scenario_type} (with_vut={with_vut})")

    # Load generated vehicles data (initial_soc, des_soc, exit_soc, etc.)
    generated_vehs = pd.read_parquet(generated_vehs_file)

    # Force numeric types for all columns except IDs
    for col in generated_vehs.columns:
        if 'id' not in col.lower():
            generated_vehs[col] = pd.to_numeric(
                generated_vehs[col], errors='coerce')

    # Load tripinfo data (duration, timeLoss, etc.)
    tripinfo_cols = ['tripinfo_id', 'tripinfo_depart', 'tripinfo_arrival',
                     'tripinfo_duration', 'tripinfo_timeLoss']
    tripinfo = pd.read_parquet(tripinfo_file, columns=tripinfo_cols)
    tripinfo = tripinfo.rename(columns={
        'tripinfo_id': 'vid',
        'tripinfo_depart': 'depart',
        'tripinfo_arrival': 'arrival',
        'tripinfo_duration': 'duration',
        'tripinfo_timeLoss': 'timeLoss'
    })

    # Force numeric types for all columns except IDs
    for col in tripinfo.columns:
        if col not in ['vid']:
            tripinfo[col] = pd.to_numeric(tripinfo[col], errors='coerce')

    # Load battery data
    battery_cols = ['timestep_time', 'vehicle_id', 'vehicle_chargingStationId',
                    'vehicle_actualBatteryCapacity', 'vehicle_maximumBatteryCapacity',
                    'vehicle_totalEnergyConsumed']
    battery = pd.read_parquet(battery_file, columns=battery_cols)
    battery = battery.rename(columns={
        'timestep_time': 'time',
        'vehicle_id': 'vid',
        'vehicle_chargingStationId': 'csid',
        'vehicle_actualBatteryCapacity': 'soc',
        'vehicle_maximumBatteryCapacity': 'Bmax',
        'vehicle_totalEnergyConsumed': 'totalEnergyConsumed'
    })

    # Force numeric types for all columns except IDs
    for col in battery.columns:
        if col not in ['vid', 'csid']:
            battery[col] = pd.to_numeric(battery[col], errors='coerce')

    # Convert SUMO's string "NULL" to proper NaN for csid
    battery['csid'] = battery['csid'].replace('NULL', np.nan)

    return generated_vehs, tripinfo, battery, with_vut


def process_battery_satis(battery, generated_vehs, tripinfo, filter_vut_only=False):
    """
    Calculate soc_gap and time_to_arrival for each vehicle timestep.

    Parameters:
    - battery: DataFrame with columns [time, vid, soc, ...]
    - generated_vehs: DataFrame with columns [vid, des_soc, ...]
    - tripinfo: DataFrame with columns [vid, arrival, ...]
    - filter_vut_only: bool - If True, filter to analyze only VUT vehicles (vid starting with 'VUT_')

    Returns:
    - result: Full DataFrame with additional columns: soc_gap, time_to_arrival
    - moments_df: DataFrame with only depart and arrival statistics per vehicle
    """
    # Filter for VUT vehicles only if requested (withVUT scenario)
    if filter_vut_only:
        vut_vids = set(
            battery[battery['vid'].str.startswith('VUT_')]['vid'].unique())
        print(f"Filtering for VUT vehicles only: {len(vut_vids)} VUT vehicles found")
        battery = battery[battery['vid'].isin(vut_vids)]
        generated_vehs = generated_vehs[generated_vehs['vid'].isin(vut_vids)]
        tripinfo = tripinfo[tripinfo['vid'].isin(vut_vids)]

    # Merge battery with generated_vehs to get des_soc
    result = battery.merge(
        generated_vehs[['vid', 'des_soc']], on='vid', how='left')

    # Merge with tripinfo to get arrival and depart times
    result = result.merge(
        tripinfo[['vid', 'arrival', 'depart']], on='vid', how='left')

    # Calculate soc_gap = des_soc - soc
    result['soc_gap'] = result['des_soc'] - result['soc']

    # Calculate time_to_arrival = arrival - time (in seconds)
    result['time_to_arrival'] = result['arrival'] - result['time']

    # Calculate normalized SOC levels (0-1 range)
    result['soc_level'] = result['soc'] / result['Bmax']
    result['des_soc_level'] = result['des_soc'] / result['Bmax']
    result['soc_gap_level'] = result['soc_gap'] / result['Bmax']

    # Calculate charge target fulfillment (satisfaction metric: 0=bad, 1=good)
    # Represents the percentage of the desired charge target that has been achieved
    result['soc_fulfillment'] = 1 - \
        ((result['des_soc_level'] - result['soc_level']) /
         result['des_soc_level'])
    # Equivalent to: result['soc_fulfillment'] = result['soc_level'] / result['des_soc_level']

    # Create small dataframe with only depart and arrival moments
    # Use groupby to get first (depart) and last (arrival) timestep for each vehicle
    depart_rows = result.groupby('vid').first().reset_index()
    depart_rows['moment'] = 'depart'

    arrival_rows = result.groupby('vid').last().reset_index()
    arrival_rows['moment'] = 'arrival'

    # Concatenate depart and arrival rows
    moments_df = pd.concat([depart_rows, arrival_rows], ignore_index=True)

    return result, moments_df


def main():
    a = parse_args()

    print(f"Loading data from {a.folder} for seed={a.seed}, hours={a.begin}-{a.end}")

    generated_vehs, tripinfo, battery, with_vut = load_data(
        a.folder, a.seed, a.begin, a.end, a.mpcInterval, a.vut)

    # Filter data by fromt (discard warm-up period)
    from_time = pd.to_datetime(a.fromt).time()
    from_seconds = from_time.hour * 3600 + from_time.minute * 60 + from_time.second

    # Filter: keep vehicles that arrived after fromt (were still active during analysis period)
    tripinfo = tripinfo[tripinfo['arrival'] >= from_seconds]

    # Filter battery data to only include vehicles present in filtered tripinfo
    valid_vids = set(tripinfo['vid'].unique())
    battery = battery[battery['vid'].isin(valid_vids)]

    print(f"Filtered data to analyze vehicles arriving after {a.fromt} ({from_seconds}s): {len(valid_vids)} vehicles")

    nick = f"_{a.nickname}" if a.nickname else ""
    print(f"Analyzing satisfaction with {a.aggregation}s aggregation")

    # Calculate soc_gap and time_to_arrival for each vehicle timestep
    # If with_vut, filter to analyze only VUT vehicles
    sdf, moments_df = process_battery_satis(
        battery, generated_vehs, tripinfo, filter_vut_only=with_vut)

    print(f"Full satisfaction dataframe shape: {sdf.shape}")
    print(f"Columns: {sdf.columns.tolist()}")
    print(f"Moments dataframe shape: {moments_df.shape}")
    print(f"Moments dataframe has {len(moments_df[moments_df['moment']=='depart'])} depart and {len(moments_df[moments_df['moment']=='arrival'])} arrival rows")

    # Save satisfaction data to parquet
    vut_suffix = f"_VUT{a.vut}"
    parquet_filename = f"satisfaction_s{a.seed}_b{a.begin}_e{a.end}_mpcInt{a.mpcInterval}{vut_suffix}{nick}.parquet"
    sdf.to_parquet(parquet_filename, index=False)
    print(f"Saved satisfaction data to {parquet_filename}")

    # Save moments data to parquet
    moments_filename = f"satisfaction_moments_s{a.seed}_b{a.begin}_e{a.end}_mpcInt{a.mpcInterval}{vut_suffix}{nick}.parquet"
    moments_df.to_parquet(moments_filename, index=False)
    print(f"Saved moments data to {moments_filename}")


if __name__ == "__main__":
    main()
