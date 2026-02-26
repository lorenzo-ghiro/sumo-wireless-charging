import os
import sys
import numpy as np
import traci  # noqa
import logging
import pandas as pd

# Control charging rate based on desired SOC with 2% hysteresis
HYSTERESIS_PERCENT = 0.02  # 2% hysteresis to prevent oscillations
DEFAULT_PON = 150000  # 150 kW in Watts

def check_sumo():
    # Always check to have sumo and sumo-tools available
    if 'SUMO_HOME' in os.environ:
        tools = os.path.join(os.
                            environ['SUMO_HOME'], 'tools')
        sys.path.append(tools)
    else:
        sys.exit("please declare environment variable 'SUMO_HOME'")
        
def apply_control(traci, need_charge_vehs, mpc_solution, vidRuntime, edge2css):
    """Apply MPC solution by setting vehicle charge rates and CS power limits."""
    
    P_dict, S_dict = None, None
    if mpc_solution:
        _, P_dict, S_dict, _ = mpc_solution
    
    # Build table for ALL vehicles in vidRuntime (on CS or not)
    table = []
    for vid in vidRuntime:
        edge = vidRuntime[vid]["edge"]
        lane = vidRuntime[vid]["lane"]
        
        # Determine power for this vehicle
        if vid in need_charge_vehs:
            PON = P_dict[vid][0] if mpc_solution else float(traci.vehicle.getParameter(vid, "device.battery.maximumChargeRate"))
        else:
            PON = 0.0  # Vehicle doesn't need charging - disable charging
        
        csid = f"{edge2css[edge]['id']}_{lane}" if edge in edge2css else None
        table.append((vid, edge, lane, PON, csid))
    
    cdf = pd.DataFrame(table, columns=["vid", "edge", "lane", "PON", "csid"])
    
    # Set vehicle charging rates for ALL vehicles (not just need_charge_vehs)
    for vid in vidRuntime:
        if vid in need_charge_vehs and mpc_solution:
            PON0 = P_dict[vid][0]  # Power from MPC
        elif vid in need_charge_vehs:
            PON0 = float(traci.vehicle.getParameter(vid, "device.battery.maximumChargeRate")) / 1000  # Keep current rate (convert W to kW)
        else:
            PON0 = 0.0  # Disable charging for vehicles that don't need it
        
        traci.vehicle.setParameter(vid, "device.battery.maximumChargeRate", str(PON0 * 1000))  # Convert kW to W
        logging.debug(f"Set vehicle {vid} maximumChargeRate to {PON0 * 1000} W")
    
    # Prepare virtual_power_W for CS power limits
    virtual_power_W = {}
    if mpc_solution:        
        virtual_power_W = {vcsid: S_dict[vcsid][0] * 1000 for vcsid in S_dict}
    else:
        for edge in edge2css:
            cs_lane0_id = edge2css[edge]['id'] + "_0"
            cs_lane1_id = edge2css[edge]['id'] + "_1"
            power0 = float(traci.chargingstation.getTotalPower(cs_lane0_id))
            power1 = float(traci.chargingstation.getTotalPower(cs_lane1_id))
            total_power = power0 + power1
            virtual_power_W[edge2css[edge]['id']] = total_power

    power_assigned = assign_total_power_with_rebalancing(virtual_power_W, cdf)
    return power_assigned

def assign_total_power_with_rebalancing(virtual_power_W, cdf):
    """Assign total power limits to charging stations, adjusting for rebalancing vehicles.
    
    Returns:
        dict: {cs_lane_id: info_dict} where info_dict contains:
              - 'allocated_W': power allocated to CS lane
              - 'requested_W': power requested by vehicles on CS lane
              - 'nveh': number of vehicles on CS lane
    """
    power_info = {}
    
    for csid in virtual_power_W:
        cs_lane0_id = f"{csid}_0"
        cs_lane1_id = f"{csid}_1"
        total_power = virtual_power_W[csid]  # in Watts
        
        # Calculate requested power and vehicle counts per lane
        lane0_vehs = cdf[cdf['csid'] == cs_lane0_id]
        lane1_vehs = cdf[cdf['csid'] == cs_lane1_id]
        
        sumPON_0_W = lane0_vehs['PON'].sum() * 1000  # W
        sumPON_1_W = lane1_vehs['PON'].sum() * 1000  # W
        sum_all_PON_W = sumPON_0_W + sumPON_1_W
        
        nveh_lane0 = len(lane0_vehs)
        nveh_lane1 = len(lane1_vehs)
        
        # Distribute power proportionally or split 50/50 if no demand
        if sum_all_PON_W > 0:
            power_lane0_W = total_power * sumPON_0_W / sum_all_PON_W
            power_lane1_W = total_power * sumPON_1_W / sum_all_PON_W
        else:
            power_lane0_W = total_power / 2.0
            power_lane1_W = total_power / 2.0
        
        traci.chargingstation.setTotalPower(cs_lane0_id, str(power_lane0_W))
        traci.chargingstation.setTotalPower(cs_lane1_id, str(power_lane1_W))
        logging.debug(f"CS {cs_lane0_id}: {power_lane0_W/1000:.2f} kW, CS {cs_lane1_id}: {power_lane1_W/1000:.2f} kW (total: {total_power/1000:.2f} kW)")
        
        # Store detailed info for logging
        power_info[f"{cs_lane0_id}_allocated_W"] = power_lane0_W
        power_info[f"{cs_lane0_id}_requested_W"] = sumPON_0_W
        power_info[f"{cs_lane0_id}_nveh"] = nveh_lane0
        
        power_info[f"{cs_lane1_id}_allocated_W"] = power_lane1_W
        power_info[f"{cs_lane1_id}_requested_W"] = sumPON_1_W
        power_info[f"{cs_lane1_id}_nveh"] = nveh_lane1
    
    return power_info
        
    
    

def parse_distribution_string(distrib_str):
    """Parse distribution string like 'U(0.1,0.9)-U(0.1,0.9)' or 'U(0.01,0.4)-U(initial_soc,1.0)'."
    
    Returns a dict with:
        - initial_soc_min, initial_soc_max: bounds for initial SOC uniform distribution
        - des_soc_min, des_soc_max: bounds for desired SOC uniform distribution
        - des_soc_depends_on_initial: True if des_soc uses 'initial_soc' as lower bound
    """
    import re
    
    # Split by '-' to get initial and desired distributions
    parts = distrib_str.split('-')
    if len(parts) != 2:
        raise ValueError(f"Distribution string must have format 'DIST1-DIST2', got: {distrib_str}")
    
    initial_str, des_str = parts
    
    # Parse initial SOC distribution: U(min,max)
    initial_match = re.match(r'U\(([0-9.]+),([0-9.]+)\)', initial_str.strip())
    if not initial_match:
        raise ValueError(f"Initial SOC distribution must be 'U(min,max)', got: {initial_str}")
    
    initial_soc_min = float(initial_match.group(1))
    initial_soc_max = float(initial_match.group(2))
    
    # Parse desired SOC distribution: U(min,max) or U(initial_soc,max)
    des_match = re.match(r'U\(([^,]+),([0-9.]+)\)', des_str.strip())
    if not des_match:
        raise ValueError(f"Desired SOC distribution must be 'U(min,max)' or 'U(initial_soc,max)', got: {des_str}")
    
    des_soc_min_str = des_match.group(1)
    des_soc_max = float(des_match.group(2))
    
    # Check if des_soc depends on initial_soc
    if des_soc_min_str == 'initial_soc':
        des_soc_depends_on_initial = True
        des_soc_min = None  # Will be set to actual initial_soc value
    else:
        des_soc_depends_on_initial = False
        des_soc_min = float(des_soc_min_str)
    
    return {
        'initial_soc_min': initial_soc_min,
        'initial_soc_max': initial_soc_max,
        'des_soc_min': des_soc_min,
        'des_soc_max': des_soc_max,
        'des_soc_depends_on_initial': des_soc_depends_on_initial
    }

def generateVehicle(vid, simtime, distrib_config=None, is_vut=False, vutisocl=1e-4):
    vtype = traci.vehicle.getTypeID(vid)
    if vtype != "soulEV65":
        raise ValueError(f"Only soulEV65 vtype is supported now")
    
    # VUTs (Vehicles Under Test) have special battery parameters
    # to observe battery discharge/recharge behavior
    if is_vut:
        # VUTs start with exact specified SOC level and want to charge to full
        initial_soc = vutisocl  # Use exact specified level
        des_soc = 1.0 
        logging.debug(f"VUT {vid} spawned with initial_soc={initial_soc:.4f}, des_soc={des_soc:.2f}")
    else:
        # Use default distribution if not provided
        if distrib_config is None:
            distrib_config = {
                'initial_soc_min': 0.01,
                'initial_soc_max': 0.4,
                'des_soc_min': None,
                'des_soc_max': 1.0,
                'des_soc_depends_on_initial': True
            }
        
        # Assign random initial battery based on distribution config
        initial_soc = np.random.uniform(distrib_config['initial_soc_min'], distrib_config['initial_soc_max'])
        
        # Assign desired SOC based on distribution config
        if distrib_config['des_soc_depends_on_initial']:
            des_soc = np.random.uniform(initial_soc, distrib_config['des_soc_max'])
        else:
            des_soc = np.random.uniform(distrib_config['des_soc_min'], distrib_config['des_soc_max'])
    
    route = traci.vehicle.getRoute(vid)
    destination = route[-1]
    entry = route[0]

    Bmax = float(traci.vehicle.getParameter(vid, "device.battery.capacity"))   # Wh
    traci.vehicle.setParameter(vid, "device.battery.chargeLevel", str(initial_soc * Bmax))

    charging_enabled = initial_soc < des_soc  # Start with charging enabled

    if not is_vut:
        logging.debug(f"Assigned initial SOC {initial_soc * Bmax:.2f} and desired SOC {des_soc * Bmax:.2f} to vehicle {vid}")

    return {
        "vid": vid,
        "vtype": vtype,
        "initial_soc": initial_soc * Bmax, # Wh
        "des_soc": des_soc * Bmax, # Wh
        "destination": destination,
        "entry": entry,
        "start_time": simtime,
        "Bmax": Bmax, # Wh
        "charging_enabled": charging_enabled,
        "is_vut": is_vut  # Track VUT status for later analysis
    }

def update_need_charge_vehs(active_veh):
    """Update charging_enabled flag for all active vehicles based on current SOC.
    
    Uses hysteresis control to prevent oscillations:
    - If soc > des_soc: disable charging
    - If soc < (des_soc - 2% of Bmax): enable charging
    - Otherwise: maintain current state
    
    Returns dict of vehicles that need charging (charging_enabled=True and soc < des_soc).
    """
    need_charge_vehs = {}
    
    for vid in active_veh.keys():
        soc = float(traci.vehicle.getParameter(vid, "device.battery.chargeLevel"))  # Wh
        des_soc = active_veh[vid]["des_soc"]  # Wh
        Bmax = active_veh[vid]["Bmax"]  # Wh
        hysteresis_threshold = HYSTERESIS_PERCENT * Bmax  # 2% of battery capacity
        
        # Implement hysteresis control
        if soc > des_soc:
            active_veh[vid]["charging_enabled"] = False
        elif soc < (des_soc - hysteresis_threshold):
            active_veh[vid]["charging_enabled"] = True
        # else: maintain current state
        
        # Collect vehicles that need charging (enabled AND below target)
        if active_veh[vid]["charging_enabled"] and soc < des_soc:
            need_charge_vehs[vid] = active_veh[vid]
    
    return need_charge_vehs

def is_internal_edge(edge) -> bool:
    """Return True if edge is internal or non-drivable infrastructure."""
    get_func = getattr(edge, "getFunction", None)
    if callable(get_func):
        func = get_func()
        return func in ("internal", "walkingarea", "crossing", "connector")
    is_int = getattr(edge, "isInternal", None)
    return bool(is_int and is_int())