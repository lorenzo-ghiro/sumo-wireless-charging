import sys
import argparse
from pathlib import Path
from xml.sax.saxutils import escape
from tabulate import tabulate
import pandas as pd

try:
    import sumolib  # comes with SUMO
except Exception:
    sys.stderr.write(
        "Error: sumolib not available. Make sure SUMO is installed and SUMO_HOME is set.\n")
    sys.exit(1)


VEHICLE_CLASSES = {
    "passenger", "private", "taxi", "bus", "coach", "delivery",
    "cargo", "truck", "trailer", "emergency", "motorcycle", "moped"
}
NON_DRIVING_CLASSES = {
    "pedestrian", "bicycle", "ship", "tram", "rail_urban", "rail", "rail_electric"
}


def is_internal_edge(edge) -> bool:
    """Return True if edge is internal or non-drivable infrastructure."""
    get_func = getattr(edge, "getFunction", None)
    if callable(get_func):
        func = get_func()
        return func in ("internal", "walkingarea", "crossing", "connector")
    is_int = getattr(edge, "isInternal", None)
    return bool(is_int and is_int())


def _lane_allowed_set(lane):
    for name in ("getAllowed", "getPermissions"):
        f = getattr(lane, name, None)
        if callable(f):
            vals = f()
            return set(vals) if vals is not None else set()
    vals = getattr(lane, "_allowed", None)
    return set(vals) if vals is not None else set()


def _lane_disallowed_set(lane):
    f = getattr(lane, "getDisallowed", None)
    if callable(f):
        vals = f()
        return set(vals) if vals is not None else set()
    vals = getattr(lane, "_disallowed", None)
    return set(vals) if vals is not None else set()


def is_vehicular_lane(lane) -> bool:
    allowed = _lane_allowed_set(lane)
    disallowed = _lane_disallowed_set(lane)

    if not allowed and not disallowed:
        get_speed = getattr(lane, "getSpeed", None)
        speed = get_speed() if callable(get_speed) else None
        return (speed is None) or (speed > 0.0)

    if not allowed:
        return len(VEHICLE_CLASSES - disallowed) > 0

    if allowed & VEHICLE_CLASSES:
        return True

    if allowed and allowed <= NON_DRIVING_CLASSES:
        return False

    return False


def gen_charging_stations_fullrightmost(net, margin, min_edge_len, nominalPower, powerbudget, efficiency):
    """
    For each non-internal edge with at least one vehicular lane,
    create a chargingStation spanning the rightmost lane (index 0),
    clamped to [margin, length - margin], and only if lane length >= min_edge_len.
    """
    totalPower, coveredspace, main_road_length = 0, 0, 0.0
    css = []
    num_cs = 0
    for edge in net.getEdges():
        if is_internal_edge(edge):
            continue

        lanes = edge.getLanes()
        if not lanes:
            continue

        rightmost = lanes[0]  # edgeId_0
        if not is_vehicular_lane(rightmost):
            continue

        # skip exit lanes
        rl_id = rightmost.getID()
        # and length < max(min_edge_len, 2 * margin):
        if ("Exit" in rl_id or "Entry" in rl_id) and ("NR" not in rl_id and "SL" not in rl_id):
            continue

        length = float(rightmost.getLength() or 0.0)
        main_road_length += length
        if length < max(min_edge_len, 2 * margin):
            continue  # too short

        # convert to int to have spire length as integer, multiple of 1m of each coil composing a spire
        start_pos = int(margin)
        end_pos = int(length - margin)
        spire_length = int(abs(end_pos - start_pos))  # [m]

        coveredspace += spire_length  # meters
        cs = {
            "id": f"cs_{num_cs}_{edge.getID()}_{rightmost.getIndex()}",
            "lane": rightmost.getID(),
            "edge": edge.getID(),
            "startPos": margin,
            "endPos": end_pos,
            "power": nominalPower*1000,  # convert kW to W (SUMO needs [W])
            "efficiency": efficiency,
            "chargeDelay": 0,
            "chargeInTransit": 1,
            "totalPower": None,
            "spire_length": spire_length
        }
        css.append(cs)
        num_cs += 1
    # Distributing powerbudget
    for cs in css:
        totalPower = powerbudget * cs['spire_length']/coveredspace
        # powerbudget was in MW, we convert to W
        cs['totalPower'] = totalPower * 10**6
    return css, coveredspace, main_road_length


def gen_charging_stations_full_lane0_lane1(net, margin, min_edge_len, nominalPower, powerbudget, efficiency):
    """
    For each non-internal edge with at least one vehicular lane,
    create chargingStations on lane 0 (rightmost) and lane 1 (if available),
    clamped to [margin, length - margin], and only if lane length >= min_edge_len.
    """
    totalPower, coveredspace, main_road_length = 0, 0, 0.0
    css = []
    num_edges_with_cs = 0
    for edge in net.getEdges():
        if is_internal_edge(edge):
            continue

        lanes = edge.getLanes()
        if not lanes:
            continue

        # Consider lane 0 and lane 1 (if exists)
        lanes_to_process = [lanes[0]]
        if len(lanes) >= 2:
            lanes_to_process.append(lanes[1])

        for lane in lanes_to_process:
            if not is_vehicular_lane(lane):
                continue

            # skip exit lanes
            lane_id = lane.getID()
            if ("Exit" in lane_id or "Entry" in lane_id) and ("NR" not in lane_id and "SL" not in lane_id):
                continue

            length = float(lane.getLength() or 0.0)

            main_road_length += length

            if length < max(min_edge_len, 2 * margin):
                continue  # too short

            if lane == lanes[0]:  # rightmost lane
                num_edges_with_cs += 1

            # convert to int to have spire length as integer, multiple of 1m of each coil composing a spire
            start_pos = int(margin)
            end_pos = int(length - margin)
            spire_length = int(abs(end_pos - start_pos))  # [m]

            coveredspace += spire_length  # meters
            cs = {
                "id": f"cs_{num_edges_with_cs}_{edge.getID()}_{lane.getIndex()}",
                "lane": lane.getID(),
                "edge": edge.getID(),
                "startPos": margin,
                "endPos": end_pos,
                "power": nominalPower*1000,  # convert kW to W (SUMO needs [W])
                "efficiency": efficiency,
                "chargeDelay": 0,
                "chargeInTransit": 1,
                "totalPower": None,
                "spire_length": spire_length
            }
            css.append(cs)

    # Distributing powerbudget
    for cs in css:
        totalPower = powerbudget * cs['spire_length']/coveredspace
        # powerbudget was in MW, we convert to W
        cs['totalPower'] = totalPower * 10**6
    return css, coveredspace, main_road_length


def write_additional_xml(stations, out_path: Path):
    def fmt_float(x):
        return f"{x:.2f}".rstrip('0').rstrip('.') if isinstance(x, float) else str(x)

    lines = ['<additional>']
    for s in stations:
        attrs = [
            f'id="{escape(str(s["id"]))}"',
            f'lane="{escape(str(s["lane"]))}"',
            f'startPos="{fmt_float(s["startPos"])}"',
            f'endPos="{fmt_float(s["endPos"])}"',
            f'power="{fmt_float(s["power"])}"',
            f'efficiency="{fmt_float(s["efficiency"])}"',
            f'chargeDelay="{fmt_float(s["chargeDelay"])}"',
            f'chargeInTransit="{fmt_float(s["chargeInTransit"])}"',
            f'totalPower="{fmt_float(s["totalPower"])}"',
        ]
        lines.append(f'    <chargingStation {" ".join(attrs)}/>')

    lines.append("</additional>\n")
    xml = "\n".join(lines)

    if out_path:
        out_path.write_text(xml, encoding="utf-8")
    else:
        sys.stdout.write(xml)


def main():
    ap = argparse.ArgumentParser(
        description="Generate cs.add.xml from a SUMO network."
    )
    ap.add_argument("--net", required=True, help="Path to net.net.xml")
    ap.add_argument("--policy", required=True, choices=["fullrightmost", "full_lane0_lane1"],
                    help="Placement policy.")
    ap.add_argument("--out", default="cs.add.xml",
                    help="Output file path or 'stdout' to print (default: cs.add.xml)")
    ap.add_argument("--margin", type=float, default=0.0,
                    help="Margin from both lane ends in meters (default: 0.5)")
    ap.add_argument("--minedgelength", type=float, default=5.0,
                    help="Minimum edge/lane length in meters (default: 5.0)")
    ap.add_argument("--nominalPower", type=float, default=100,
                    help="Nominal power of generated CS (default: 100 kW)")
    ap.add_argument("--powerbudget", type=float, default=10,
                    help="Power budget to be distributed among all spires [MW]")
    ap.add_argument("--efficiency", type=float,
                    default=0.95, help="CS efficiency")
    args = ap.parse_args()

    net_path = Path(args.net)
    if not net_path.exists():
        sys.stderr.write(f"Error: network not found: {net_path}\n")
        sys.exit(2)

    try:
        net = sumolib.net.readNet(str(net_path))
    except Exception as e:
        sys.stderr.write(f"Error parsing network: {e}\n")
        sys.exit(3)

    if args.policy == "fullrightmost":
        stations, coveredspace, main_road_length = gen_charging_stations_fullrightmost(
            net, args.margin, args.minedgelength, args.nominalPower, args.powerbudget, args.efficiency)
    elif args.policy == "full_lane0_lane1":
        stations, coveredspace, main_road_length = gen_charging_stations_full_lane0_lane1(
            net, args.margin, args.minedgelength, args.nominalPower, args.powerbudget, args.efficiency)
    else:
        sys.stderr.write("Policy not implemented.\n")
        sys.exit(4)

    out_path = None if args.out.lower() == "stdout" else Path(args.out)
    write_additional_xml(stations, out_path)
    assert main_road_length > coveredspace
    covered_fraction = coveredspace / main_road_length
    coveredspace /= 10**3  # convert m to km
    main_road_length /= 10**3  # convert m to km
    print(f"{len(stations)} charginStations defined in {out_path}\n")
    print(f"Coveredspace={round(coveredspace,2)}km out of {round(main_road_length,2)}km of road_length")
    print(f"coverage of {round(covered_fraction*100,2)}%")

    df = pd.DataFrame(stations)
    df['totalPower'] = df['totalPower']/10**3  # W to kW
    df = df.sort_values('spire_length')

    if args.policy == "full_lane0_lane1":
        tmp = df.groupby("edge")[
            ['spire_length', 'totalPower']].sum().reset_index()
        tmp['spire_length'] = tmp['spire_length'] / 2.0
        df = tmp

    print(tabulate(df[['edge', 'spire_length', 'totalPower']], headers=[
          'edge', 'spire_length [m]', 'totalPower [kW]'], tablefmt='github', floatfmt=".2f"))

    # print(tabulate(tmp[['spire_length', 'totalPower']], headers=[
    #       'spire_length [m]', 'totalPower [kW]'], tablefmt='latex', floatfmt=".2f"))


if __name__ == "__main__":
    main()
