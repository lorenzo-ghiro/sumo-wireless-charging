import sys
import optparse
import logging
import numpy as np
import pandas as pd
import random

from src.mpc_solver import MPCS
from src import sumoparser as sumop
from src import myutils as mu
mu.check_sumo()
from sumolib import checkBinary  # noqa
import sumolib
import traci  # noqa
import traci.constants as tc


MAX_TAU_HORIZON = 2*60 # 4 minutes in seconds (we have a 5km road that we travel approx at 50km/h, we should finsih in ~6 minutes)

def get_args():
    optParser = optparse.OptionParser()
    optParser.add_option("-c", "--sumoconfig", dest="sumoconfig",
                         help="path to sumo cfg file to load", default="istanbul.sumo.cfg")
    optParser.add_option("-t", "--chargingStations", dest="chargingStations", default="src/cs.add.xml",
                         help="path to chargingStations xml file")
    optParser.add_option("-n", "--net", dest="net", default="src/net.net.xml",
                         help="path to SUMO network file")
    optParser.add_option("-f", "--flowfile", dest="flowfile", default="src/flows/flow_17_18_vpm27.xml",
                         help="path to sumo flow file to pass as demand file")
    optParser.add_option("--nogui", action="store_true",
                         default=False, help="run the commandline version of sumo")
    optParser.add_option("--debug", action="store_true", default=False)
    optParser.add_option("-m", "--mpcInterval", dest="mpcInterval", default=10, type=int,
                         help="interval (in seconds) at which MPC optimization is performed. Negative value for disabling MPC")
    optParser.add_option("-b", "--begin", dest="begin")
    optParser.add_option("-e", "--end", dest="end")
    optParser.add_option("-s", "--seed", dest="seed", default=1234, type=int)
    optParser.add_option("--output-prefix", dest="outprefix")
    optParser.add_option("--distrib", dest="distrib", default="U(0.01,0.4)-U(initial_soc,1.0)",
                         help="Distribution string for initial_soc and des_soc, e.g., 'U(0.1,0.9)-U(0.1,0.9)' or 'U(0.01,0.4)-U(initial_soc,1.0)'")
    optParser.add_option("--vutisocl", dest="vutisocl", default=1e-4, type=float,
                         help="VUT initial SOC level (default: 1e-4)")
    optParser.add_option("--fromt", dest="fromt", default=None,
                         help="Time to start control (format HH:MM:SS). Control is disabled before this time.")
    options, args = optParser.parse_args()
    return options




def run(mpcInterval, edge2css, eta, net, beginTime=None, endTime=None, distrib_config=None, vutisocl=1e-4, fromtTime=None):
    step = 0
    active_veh, need_charge_vehs = {}, {}
    
    # Log fromt configuration
    if fromtTime is not None:
        logging.info(f"Control will be activated only after fromt={fromtTime}s")
    
    # Precompute useful things once (constant throughout simulation)
    lane2length = {l: traci.lane.getLength(l) for l in traci.lane.getIDList()}
    # needRebalance = {edge:cs for edge, cs in edge2css.items() if edge2numLanes[edge] > 1}
    
    # Progress tracking for logging
    next_progress_milestone = 1 if (beginTime is not None and endTime is not None) else None
    
    # Track CS power assignments over time
    cs_power_log = []
    
    MPC_ENABLED = mpcInterval > 0

    if MPC_ENABLED:
        mpcs = MPCS(traci, eta, edge2css, mpcInterval, lane2length)
        last_mpc_time = 0.0
        controlInterval = -1
    else:
        controlInterval = mpcInterval * -1
        last_control_time = 0.0

    generated_vehs = {}

    # Define subscription constants for vehicle data
    VEHICLE_SUBSCRIPTIONS = [tc.VAR_ROAD_ID, tc.VAR_LANE_INDEX]

    while traci.simulation.getMinExpectedNumber() > 0:
        simtime = traci.simulation.getTime()

        if endTime is not None and simtime >= endTime:
            logging.info(f"Reached end time {endTime}s at step {step}, terminating simulation")
            break
        
        # Log progress every 1%
        if endTime is not None and next_progress_milestone is not None:
            current_progress = ((simtime - beginTime) / (endTime - beginTime)) * 100
            if current_progress >= next_progress_milestone:
                print(f"Progress: {next_progress_milestone}% (time: {simtime:.1f}s / {endTime}s, step: {step}, vehicles: {len(active_veh)})", file=sys.stderr)
                next_progress_milestone += 1
                if next_progress_milestone > 100:
                    next_progress_milestone = None  # Stop checking after 100%

        traci.simulationStep()

        # Customize newly departed vehicles, remove arrived ones
        departed = set(traci.simulation.getDepartedIDList())
        arrived = set(traci.simulation.getArrivedIDList())
        assert len(departed.intersection(arrived)) == 0, "A vehicle cannot depart and arrive in the same step"

        for vid in departed:
            # Detect VUTs (Vehicles Under Test) by flow ID prefix
            is_vut = vid.startswith("VUT_")
            veh_data = mu.generateVehicle(vid, simtime, distrib_config=distrib_config, is_vut=is_vut, vutisocl=vutisocl)
            active_veh[vid] = veh_data
            generated_vehs[vid] = veh_data
            traci.vehicle.subscribe(vid, VEHICLE_SUBSCRIPTIONS)

        for vid in arrived:
            # No need to explicitly unsubscribe - TraCI handles it automatically
            del active_veh[vid]
            if vid in need_charge_vehs:
                del need_charge_vehs[vid]


        # Apply control only if fromt condition is met
        control_active = (fromtTime is None) or (simtime >= fromtTime)
        
        if (not MPC_ENABLED and control_active and (simtime - last_control_time) >= controlInterval 
            and step > 0 and len(active_veh) > 0):     
            
            need_charge_vehs = mu.update_need_charge_vehs(active_veh)
            # Apply charging rates based on updated flags
            for vid in active_veh.keys():
                PON = mu.DEFAULT_PON if active_veh[vid]["charging_enabled"] else 0.0
                traci.vehicle.setParameter(vid, "device.battery.maximumChargeRate", str(PON))
            
            last_control_time = simtime
        
        mpc_solution = None
        if (MPC_ENABLED and control_active and (simtime - last_mpc_time) >= mpcInterval and step > 0 and len(active_veh) > 0):
            assert set(traci.vehicle.getIDList()) == set(active_veh.keys())
            logging.info(f"Invoking MPC solver at time {simtime}s (step={step}), {len(active_veh)} vehicles")
            
            non_internal_edges = [edge.getID() for edge in net.getEdges() if not mu.is_internal_edge(edge)]
            e2t = {e:min(traci.edge.getTraveltime(e), MAX_TAU_HORIZON) for e in non_internal_edges}
            last_mpc_time = simtime

            need_charge_vehs = mu.update_need_charge_vehs(active_veh)
            logging.info(f"MPC solver invoked for {len(need_charge_vehs)} vehicles that need charging")
            mpc_solution = mpcs.compute_mpc_solution(need_charge_vehs, e2t)
        
                
        # process subscription results
        vidRuntime = {}
        subscription_results = traci.vehicle.getAllSubscriptionResults()
        for vid in active_veh.keys():
            if vid in subscription_results:
                sub_data = subscription_results[vid]
                vid_record = {
                    "time": simtime,
                    "edge": sub_data.get(tc.VAR_ROAD_ID, ""),
                    "lane": sub_data.get(tc.VAR_LANE_INDEX, -1)}
                vidRuntime[vid] = vid_record
        
        # Set solution
        if (len(active_veh) > 0):
            power_assigned = mu.apply_control(traci, need_charge_vehs, mpc_solution, vidRuntime, edge2css)
            if power_assigned:
                record = {'time': simtime}
                record.update(power_assigned)
                cs_power_log.append(record)

        step += 1

    traci.close()
    sys.stdout.flush()

    return generated_vehs, cs_power_log


if __name__ == "__main__":
    args = get_args()

    sumoe = "sumo" if args.nogui else "sumo-gui"
    sumoBinary = checkBinary(sumoe)

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    if args.debug:
        logger.setLevel(logging.DEBUG)

    cmd = [sumoBinary, "-c", args.sumoconfig, "--route-files", args.flowfile,
           "--seed", str(args.seed), "-b", args.begin, "-e", args.end, "--output-prefix", args.outprefix]
    print(" ".join(map(str, cmd)))

    # set seed for python libraries
    np.random.seed(args.seed)
    random.seed(args.seed)

    # args.begin and args.end must be in format "HH:MM:SS"
    parts_begin = args.begin.split(":")
    beginTime = int(parts_begin[0]) * 3600 + int(parts_begin[1]) * 60 + int(parts_begin[2])
    
    parts = args.end.split(":")
    endTime = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

    traci.start(cmd)

    # Parse network
    net = sumolib.net.readNet(args.net)
    logging.info(f"Parsed network from {args.net}")

    edge2numLanes = {edge.getID(): edge.getLaneNumber() for edge in net.getEdges() if not mu.is_internal_edge(edge)}

    # Parse distribution configuration
    distrib_config = mu.parse_distribution_string(args.distrib)
    logging.info(f"Using distribution config: {distrib_config}")

    edge2css, parsed_eta = sumop.parse_charging_stations(args.chargingStations)
    
    # Parse fromt if provided
    fromtTime = None
    if args.fromt is not None:
        parts_fromt = args.fromt.split(":")
        fromtTime = int(parts_fromt[0]) * 3600 + int(parts_fromt[1]) * 60 + int(parts_fromt[2])
        logging.info(f"Control activation time (fromt): {args.fromt} ({fromtTime}s)")
    
    generated_vehs, cs_power_log = run(
        args.mpcInterval, edge2css, parsed_eta, net, beginTime, endTime, distrib_config, args.vutisocl, fromtTime)

    # Save generated vehicles data (always)
    if generated_vehs:
        gen_vehs_df = pd.DataFrame(list(generated_vehs.values()))
        print(f"Saving generated vehicles to {args.outprefix}generated_vehs.parquet")
        gen_vehs_df.to_parquet(f"{args.outprefix}generated_vehs.parquet", index=False)
    
    # Save CS power assignments log
    if cs_power_log:
        cs_power_df = pd.DataFrame(cs_power_log)
        print(f"Saving CS power assignments to {args.outprefix}cs_power_assigned.parquet")
        cs_power_df.to_parquet(f"{args.outprefix}cs_power_assigned.parquet", index=False)
