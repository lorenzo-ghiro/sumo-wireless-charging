from sumolib.xml import parse


def parse_charging_stations(csxmlfile):
    edge2cs = {}
    efficiencies = []
    for cs in parse(csxmlfile, 'chargingStation'):
        # Extract edge from lane: "eN2S_4_0" -> "eN2S_4"
        lane_id = cs.lane
        edge = lane_id.rsplit("_", 1)[0]  # Remove last "_X" suffix
        
        efficiency = float(cs.efficiency)
        efficiencies.append(efficiency)
        
        totalPower = float(getattr(cs, "totalPower", 0.0))
        
        # If edge already exists, sum totalPower (multiple lanes on same edge)
        if edge in edge2cs:
            edge2cs[edge]["totalPower"] += totalPower
        else:
            mycs = {
                "id": cs.id[:-2],
                "edge": edge,
                "startPos": float(cs.startPos),
                "endPos": float(cs.endPos),
                "length": float(cs.endPos) - float(cs.startPos),
                "power": float(cs.power),
                "efficiency": efficiency,
                "chargeDelay": int(cs.chargeDelay),
                "chargeInTransit": int(cs.chargeInTransit),
                "totalPower": totalPower,
            }
            edge2cs[edge] = mycs
    
    unique_efficiencies = set(efficiencies)
    assert len(unique_efficiencies) == 1, f"All charging stations must have the same efficiency, found: {unique_efficiencies}"
    parsed_eta = list(unique_efficiencies)[0]
    assert 0 <= parsed_eta <= 1, f"Efficiency must be between 0 and 1, found: {parsed_eta}"
    return edge2cs, parsed_eta
