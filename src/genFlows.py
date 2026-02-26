import argparse


'''
To get a Poisson distrib with mean Lambda veh per sec, SUMO works like this!!!
https://sumo.dlr.de/docs/Simulation/Randomness.html#poisson_distribution
'''


def print_flow(orig, dest, b, e, Lambda, f):
    flow_id = f"{orig}_{dest}"
    f.write(
        f'  <flow id="{flow_id}" '
        f'from="{orig}" to="{dest}" '
        f'type="soulEV65" begin="{b}" end="{e}" '
        f'departLane="best" departSpeed="max" departPos="base" '
        f'period="exp({Lambda:.6f})"/>\n'
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate SUMO flow definitions from a target vehicles-per-minute rate.")
    parser.add_argument("--vpm", type=int, required=True,
                        help="Lambda: vehicles per minute per lane",)
    parser.add_argument("--vtype", type=str, default="soulEV65")
    parser.add_argument("--begin", type=int, required=True, choices=list(range(0, 24)),
                        help="Begin time as hour of day (e.g., 17 for 17:00)")
    parser.add_argument("--end", type=int, required=True, choices=list(range(0, 24)),
                        help="End time as hour of day (e.g., 18 for 18:00)")
    parser.add_argument("--vutinterval", type=int, default=60,
                        help="Deterministic interval in seconds for spawning VUT (Vehicles Under Test), default: 60s")
    parser.add_argument("--novut", action="store_true",
                        help="Skip generation of VUT (Vehicles Under Test) flows")
    args = parser.parse_args()

    # Convert vehicles per minute to probability x lane [1/s]
    vps = args.vpm / 60.0
    Lambda = vps

    middle = Lambda / 8.0
    ms = Lambda / 4.0
    main = Lambda / 2.0

    flows = [
        # North -> South (base)
        ("NLe", "ExitMN", middle),
        ("NLe", "ExitM",  middle),
        ("NLe", "ExitMS", ms),
        ("NLe", "ExitSL", main),

        # South -> North (base)
        ("SRe", "ExitMS", ms),
        ("SRe", "ExitM",  middle),
        ("SRe", "ExitMN", middle),
        ("SRe", "ExitNR", main),

        # Re-introduction: North->South traffic that "exits" at middle points re-enters and goes to South
        ("EntryMN", "ExitSL", middle),
        ("EntryM",  "ExitSL", middle),
        ("EntryMS", "ExitSL", ms),

        # Re-introduction: South->North traffic that "exits" at middle points re-enters and goes to North
        ("EntryMN", "ExitNR", middle),
        ("EntryM",  "ExitNR", middle),
        ("EntryMS", "ExitNR", ms),
    ]

    vut_suffix = 0 if args.novut else args.vutinterval
    outxml = f"flows/flow_{args.begin}_{args.end}_vpm{args.vpm}_VUT{vut_suffix}.xml"
    with open(outxml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<routes>\n')

        b, e = int(args.begin) * 3600, int(args.end) * 3600
        for orig, dest, lam in flows:
            print_flow(orig, dest, b, e, lam, f)

        if not args.novut:
            # Add VUT (Vehicles Under Test) flows with deterministic period
            # VUT flow 1: North to South (full route)
            f.write(
                f'  <flow id="VUT_NLe_ExitSL" '
                f'from="NLe" to="ExitSL" '
                f'type="soulEV65" begin="{b}" end="{e}" '
                f'departLane="best" departSpeed="max" departPos="base" '
                f'period="{args.vutinterval}"/>\n'
            )

            # VUT flow 2: South to North (full route)
            f.write(
                f'  <flow id="VUT_SRe_ExitNR" '
                f'from="SRe" to="ExitNR" '
                f'type="soulEV65" begin="{b}" end="{e}" '
                f'departLane="best" departSpeed="max" departPos="base" '
                f'period="{args.vutinterval}"/>\n'
            )

        f.write('</routes>\n')
    vut_msg = f"with VUT flows (interval={args.vutinterval}s)" if not args.novut else "without VUT flows"
    print(f"{outxml} written {vut_msg}.")


if __name__ == "__main__":
    main()
