import cvxpy as cp
import numpy as np
import traci  # noqa
from math import ceil
import pandas as pd
import logging
from itertools import product

ENERGY_PRICE_WEIGHT = 1e-2 # Weight for energy cost in objective
PRICE_OF_ENERGY = 0.1 # Euro/kWh
COIL_NOMINAL_POWER_kW = 100.0 # kW
MIN_STRIPE_POWER_kW = 100.0 # kW
MAX_TAU_HORIZON = 2*60 # 4 minutes in seconds (we have a 5km road that we travel approx at 50km/h, we should finsih in ~6 minutes)
MAXT = 12 # Max number of MPC steps (for padding purposes, should be >= MAX_TAU_HORIZON / DeltaT)


CONSUMPTION_WH = 0.0 # consumption per DeltaT in Wh, to be defined according to vehicle model
MOF = 4 # Max Overbooking Factor
POWER_STRIPE_WEIGHT = 1e-3 # Weight for power stripe deviation in objective
MAXIMUM_CHARGE_RATE_KW = 150.0 # kW, maximum charge rate for any vehicle (for clipping PON values)
# OVERPROV = 0.05 # Overprovisioning factor to compensate for prediction errors (5%)

class MPCS:
    def __init__(self, traci, COIL_ETA, S, DeltaT, lane2length):
        self.traci = traci
        self.COIL_ETA = COIL_ETA
        self.S = S  # stripes
        self.DeltaT = DeltaT
        self.l2l = lane2length  # Lane ID to length mapping
        
        # Pre-compile the CVXPY problem with parameters
        self.problem = None
        self.params = None
        self.variables = None
        self._setup_cvxpy_problem()

    def predict_pos_atTime(self, vehID, T, pred_time2arr):
        # is time offset from now
        if T > pred_time2arr:
            raise ValueError("T exceeds predicted arrival time")

        remaining = T
        route = traci.vehicle.getRoute(vehID)
        idx = traci.vehicle.getRouteIndex(vehID)

        if not route or idx < 0:
            raise ValueError("Route or index unavailable")

        edgeID = route[idx]
        cur_lane = traci.vehicle.getLaneID(vehID)
        cur_pos = traci.vehicle.getLanePosition(vehID)

        cur_len = max(self.l2l[cur_lane], 1e-6)
        tt = max(self.e2t[edgeID], 1e-9)

        residual_length = max(cur_len - cur_pos, 0.0)
        edge_time = tt * (residual_length / cur_len)
        assert edge_time > 0.0, "Edge time must be positive"

        while remaining > edge_time:
            remaining -= edge_time
            idx += 1
            assert idx < len(route), "Index exceeds route length"

            edgeID = route[idx]
            edge_time = max(self.e2t[edgeID], 1e-9)
            cur_len = self.l2l[f"{edgeID}_0"]
            residual_length = cur_len
            cur_pos = 0.0

        frac = remaining / edge_time
        assert 0.0 <= frac < 1.0, "Residual edge to be traveled must be less than full edge"
        pos = cur_pos + residual_length * frac
        assert 0.0 <= pos <= cur_len

        return edgeID, pos

    def predicted_time_to_arrival(self, vehID):
        # current state
        route = traci.vehicle.getRoute(vehID)
        # index of current edge in route
        idx = traci.vehicle.getRouteIndex(vehID)
        lane = traci.vehicle.getLaneID(vehID)
        pos = traci.vehicle.getLanePosition(vehID)  # [m] from lane start

        if not route or idx < 0:
            raise ValueError("Not able to predict travel time")

        # 1) remaining part of the current edge
        cur_edge = route[idx]
        edge_len = self.l2l[lane]
        assert edge_len >= pos
        rem_len = edge_len - pos
        full_tt = max(0.0, self.e2t[cur_edge])

        # scale current-edge time by remaining fraction (simple but effective)
        assert edge_len > 0.0, "Edge length must be positive"
        cur_edge_time = full_tt * (rem_len / edge_len)

        # 2) full remaining edges
        residual_edges = route[idx+1:]
        residual_time = sum(max(0.0, self.e2t[e])
                            for e in residual_edges)

        tau = cur_edge_time + residual_time
        return min(tau, MAX_TAU_HORIZON)

    def find_cs_on_position(self, edge_id, pos, eps=1e-6):
        try:
            cs = self.S[edge_id]

            if cs["startPos"] - eps <= pos <= cs["endPos"] + eps:
                return cs["id"]
        except KeyError:
            return None
        return None

    def predict_trajectory_efficient(self, vehID, pred_time2arr, DT):
        """Predict all positions for a vehicle up to arrival time efficiently.
        
        Simulates vehicle movement by advancing DT * edgeSpeed at each step.
        When position exceeds edge length, vehicle moves to next edge.
        
        Returns list of (timestep_k, edge_id, position, csid) and TerminalIndex
        """
        route = self.traci.vehicle.getRoute(vehID)
        idx = self.traci.vehicle.getRouteIndex(vehID)
        
        if not route or idx < 0:
            return [], 1
        
        # Initial state from TraCI
        cur_pos = self.traci.vehicle.getLanePosition(vehID)
        
        # Calculate TerminalIndex (number of DT steps to simulate)
        TerminalIndex = ceil(pred_time2arr / DT)
        trajectory = []
        
        # State variables for simulation
        edge_idx = idx  # Current edge index in route
        pos = cur_pos  # Current position on edge [m]
        
        # Simulate DT steps
        for k in range(1, TerminalIndex):
            if edge_idx >= len(route):
                break
            
            # Get current edge info
            edge = route[edge_idx]
            edge_len = self.l2l[f"{edge}_0"]
            edge_tt = max(self.e2t[edge], 1e-9)
            edgeSpeed = edge_len / edge_tt  # [m/s]
            
            # Calculate advancement for this DT step
            avanzamento = DT * edgeSpeed
            new_pos = pos + avanzamento
            
            # Handle edge transitions (may cross multiple edges if DT is large)
            while new_pos > edge_len and edge_idx < len(route) - 1:
                # Overflow: move to next edge
                new_pos = new_pos - edge_len
                edge_idx += 1
                
                # Update edge info for the new edge
                edge = route[edge_idx]
                edge_len = self.l2l[f"{edge}_0"]
            
            # Update position (clamp to edge length if at final edge)
            pos = min(new_pos, edge_len)
            
            # Record trajectory at this timestep
            if edge_idx < len(route):
                edge = route[edge_idx]
                csid = self.find_cs_on_position(edge, pos)
                trajectory.append((k, edge, pos, csid))
        
        return trajectory, TerminalIndex


    def prepare_problem_variables(self, V):
        # Compute expected residual travelling times per vehicle (Tau_i)
        Tau = {vid: self.predicted_time_to_arrival(vid) for vid in V}

        # Compute Gamma_i,c,t indication function predicting where
        # vehicles will be at step t, thus, if they will be or not over some coil
        DT = self.DeltaT
        gamma_table = []
        TerminalIndeces = {}
        
        for vid in V:
            # Add current state of vehicle
            cur_edge = self.traci.vehicle.getRoadID(vid)
            cur_pos = self.traci.vehicle.getLanePosition(vid)
            csid0 = self.find_cs_on_position(cur_edge, cur_pos)
            gamma_table.append([0, vid, csid0])
            
            # Predict entire trajectory efficiently
            pred_time2arr = Tau[vid]
            trajectory, TerminalIndex = self.predict_trajectory_efficient(vid, pred_time2arr, DT)
            TerminalIndeces[vid] = min(TerminalIndex, MAXT)  # Cap TerminalIndex to MAXT for padding
            
            # Add trajectory to gamma table
            for k, edge, pos, csid in trajectory:
                if k < MAXT:  # Append only up to MAXT-1 for computational tractability (P has indices 0 to maxT-1)
                    gamma_table.append([k, vid, csid])

        GT = pd.DataFrame(gamma_table, columns=["k", "vid", "csid"])
        return TerminalIndeces, GT, Tau

    def get_battery_stats(self, V):
        B0, Bdes, Bmax, PonMAX = [], [], [], []
        for vehID in V:
            capacity = V[vehID]["Bmax"] # Wh
            currentCharge = float(traci.vehicle.getParameter(vehID, "device.battery.chargeLevel")) # Wh
            B0.append(currentCharge / capacity) # SOC level in [0,1]
            Bdes.append(V[vehID]["des_soc"] / capacity) # desired SOC in [0,1]
            Bmax.append(capacity) # Wh
            PonMAX.append(MAXIMUM_CHARGE_RATE_KW) # should be 150 kW
        return B0, Bdes, Bmax, PonMAX # [0,1], [0,1], Wh, kW

    def getTotalPowerOfCS_kW(self, csid):
        for edge, cs in self.S.items():
            if cs["id"] == csid:
                return cs["totalPower"] / 1000.0  # Convert W to kW
        raise ValueError(f"Charging station id {csid} not found")

    def _setup_cvxpy_problem(self):
        """Setup the CVXPY problem structure - will be rebuilt dynamically."""
        # Note: We'll use a simpler approach where we rebuild the problem
        # but cache repeated computations and use warm start
        logging.info(f"CVXPY solver initialized with warm start enabled")
        self.last_solution = None  # Store last solution for warm start

    def get_avg_consumption_vector(self, V, now, DeltaT):
        """Compute consumption vector for vehicles over the MPC horizon."""
        Consumptions = []
        for vid in V:
            # For simplicity, assume constant consumption per DeltaT
            # In practice, this could be based on speed, acceleration, etc.
            eConsTot = float(traci.vehicle.getParameter(vid, "device.battery.totalEnergyConsumed"))
            avgCons = min(max(eConsTot * DeltaT / (now - V[vid]["start_time"]), 0.15 * DeltaT), 10.0 * DeltaT)  # Wh
            Consumptions.append(avgCons) # Wh
        return Consumptions
            

    def compute_mpc_solution(self, V, edge2travelTime):
        # Store edge to travel time mapping for use in predictions
        self.e2t = edge2travelTime
        
        now = traci.simulation.getTime()
        logging.debug(f"Solution to be computed at time {now}")

        TerminalIndeces, GT, Tau = self.prepare_problem_variables(V)        
        logging.debug(f"Gamma table size: {len(GT)} rows for {len(V)} vehicles")
        nv, _ = len(V), len(self.S)
        # per-vehicle terminal indices (Ti)
        T = list(TerminalIndeces.values())
        
        DeltaT = self.DeltaT

        # Variables with ragged horizons:
        maxT = min(max(T), MAXT)  # Max horizon for padding, should be >= MAX_TAU_HORIZON / DeltaT
        logging.info(f"Problem size: {nv} vehicles, maxT={maxT}, total vars={(nv * maxT) + (nv * (maxT+1))}")
        # Power assingment (per veh, per MPC step)
        P = cp.Variable((nv, maxT), nonneg=True) # kW
        # Battery charge levels (per veh, per MPC step) in [0,1]
        B = cp.Variable((nv, maxT+1), nonneg=True)
        # Stripe control variable
        S = cp.Variable((len(self.S), maxT), nonneg=True)

        B0, Bdes, Bmax, PonMAX = self.get_battery_stats(V) # soc level in [0,1], [0,1], Wh, kW
        Consumptions = self.get_avg_consumption_vector(V, now, DeltaT) # Wh

        
        constraints = []
        # constraints += [B <= 1.0]  # battery cannot exceed max capacity
        for i, vid in enumerate(V):
            constraints += [B[i,0] == B0[i]]  # initial SOC
            constraints += [B[i,:] <= Bdes[i]]  # battery (for each veh i) cannot exceed its desired SOC
            for k in range(1, T[i]+1):
                # Battery dynamics
                # P is in kW, DeltaT in seconds, Bmax in Wh
                # P * DeltaT gives kWs, need to convert to Wh: divide by 3600
                constraints += [
                    B[i,k] == B[i,k-1] + self.COIL_ETA * P[i,k-1] * 1000 * DeltaT / (3600 * Bmax[i]) - (Consumptions[i] / Bmax[i])
                ]
            for k in range(T[i]+1, maxT+1):
                constraints += [B[i,k] == B[i,T[i]]]  # no change after arrival
            # Power limits
            constraints += [P[i,:T[i]] <= min(COIL_NOMINAL_POWER_kW, PonMAX[i])]
            if T[i] < maxT:
                constraints += [P[i,T[i]:] == 0.0]  # no power after arrival
        
        # mappings for retrieving indices of vehicles and stripes
        vid_to_index = {vid: i for i, vid in enumerate(V)}
        stripe_to_index = {cs['id']: i for i, cs in enumerate(self.S.values())}

        TOTBUDGET_kW = sum(cs["totalPower"] / 1000.0 for cs in self.S.values())
        assert len(self.S) * MIN_STRIPE_POWER_kW <= TOTBUDGET_kW, f"Infeasible problem: not enough total power {TOTBUDGET_kW}kW to meet minimum stripe power requirements {len(self.S) * MIN_STRIPE_POWER_kW}kW"
        constraints += [S >= MIN_STRIPE_POWER_kW]
        
        # add power stripe constraints
        power_stripe = 0
        grouped = GT.groupby(['csid', 'k'])
        power_sums = {} 
        for (csid, k), group in grouped:
            if csid is not None:  # Skip is csid is None (aka veh not on a cs at this step)
                vehicles_at_this_cs_k = group['vid'].tolist()
                indices = [vid_to_index[vid] for vid in vehicles_at_this_cs_k]
                
                power_sum = cp.sum(cp.hstack([P[i, k] for i in indices]))
                power_sums[(csid, k)] = power_sum
                
                power_stripe += cp.square(S[stripe_to_index[csid], k] - power_sum)
                constraints += [power_sum <= S[stripe_to_index[csid], k]]
        
        all_csk_pairs = set(product(stripe_to_index.keys(), range(maxT)))
        defined_powersums = set(power_sums.keys())
        undefined_powersums = all_csk_pairs.difference(defined_powersums)
        for (csid, k) in undefined_powersums:
            power_stripe += cp.square(S[stripe_to_index[csid], k] - MIN_STRIPE_POWER_kW)
        
        for csid,i in stripe_to_index.items():
            constraints += [S[i,:] <= MOF * self.getTotalPowerOfCS_kW(csid)]
        
        for k in range(maxT):
            constraints += [cp.sum(S[:, k]) == TOTBUDGET_kW]

        # Objective: minimize quadratic deviation from desired SOC at arrival + penalty on energy cost       
        # Compute urgency weight for each vehicle
        tau_min = 0.25  # Small positive value to avoid division by zero
        urgency = []
        for i, vid in enumerate(V):
            tau_v = Tau[vid]
            b_des = Bdes[i]
            b_0 = B0[i]
            # [x]+ means max(x, 0)
            u_v = max(b_des - b_0, 0) / max(tau_v, tau_min)
            urgency.append(u_v)
        
        # Vectorized quadratic term with urgency
        # Create a weight matrix (nv x maxT+1) where weight[i,k] = urgency[i] if k <= T[i], else 0
        weight_matrix = np.zeros((nv, maxT+1))
        for i in range(nv):
            weight_matrix[i, :T[i]+1] = urgency[i]
        
        # Create Bdes matrix by broadcasting Bdes to (nv, maxT+1)
        Bdes_matrix = np.tile(np.array(Bdes).reshape(-1, 1), (1, maxT+1))
        
        # Vectorized quadratic term using element-wise operations
        quadratic_term = cp.sum(cp.multiply(weight_matrix, cp.square(B - Bdes_matrix)))

        energy_cost = ENERGY_PRICE_WEIGHT * PRICE_OF_ENERGY * DeltaT * cp.sum(P)
        
        objective = cp.Minimize(quadratic_term - energy_cost + POWER_STRIPE_WEIGHT * power_stripe)
        prob = cp.Problem(objective, constraints)

        # Solve with best available solver: GUROBI > SCS > OSQP
        solver_used = None
        try:
            # Try GUROBI first (commercial solver, best performance)
            result = prob.solve(solver=cp.GUROBI, verbose=False, warm_start=True)
            solver_used = "GUROBI"
        except (cp.error.SolverError, ModuleNotFoundError, Exception) as e:
            # Catch all exceptions including gurobipy.GurobiError (license issues)
            try:
                # Try SCS (better for large-scale problems than OSQP)
                result = prob.solve(solver=cp.SCS, verbose=False, warm_start=True, 
                                   eps_abs=1e-4, eps_rel=1e-4, max_iters=10000)
                solver_used = "SCS"
            except (cp.error.SolverError, ValueError) as e2:
                logging.warning(f"SCS solver failed: {e2}, falling back to OSQP with increased iterations")
                # Fallback to OSQP with more iterations
                result = prob.solve(solver=cp.OSQP, verbose=False, warm_start=True,
                                   max_iter=50000, eps_abs=1e-4, eps_rel=1e-4)
                solver_used = "OSQP"

        if prob.status not in ['optimal', 'optimal_inaccurate']:
            logging.error(f"{solver_used} failed with status: {prob.status}")
            raise ValueError(f"MPC solver failed with status: {prob.status}")
        
        logging.info(f"Solved MPC problem with {solver_used}, objective: {result}, status: {prob.status}")

        # Convert P.value and S.value to dictionaries with vehicle/CS IDs as keys
        P_dict = {vid: P.value[vid_to_index[vid], :] for vid in V}
        S_dict = {csid: S.value[i, :] for csid, i in stripe_to_index.items()}
        
        # # Apply overprovisioning to compensate for prediction errors
        # P_dict_over = {vid: P_values * (1 + OVERPROV) for vid, P_values in P_dict.items()}
        # logging.debug(f"Applied {OVERPROV*100:.1f}% overprovisioning to vehicle charge rates")
        
        return result, P_dict, S_dict, GT


       