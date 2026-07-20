#!/usr/bin/env python3
"""Orchid-style chord processor: hold a modifier key, play a root, get a chord."""

import argparse

import mido

from chords import ChordEngine, ZONE_BASE


def pick_port(names, wanted):
    """Resolve a port by numeric index or case-insensitive name substring."""
    if wanted.isdigit():
        index = int(wanted)
        if 0 <= index < len(names):
            return names[index]
        raise SystemExit(f"port index {wanted} out of range (0-{len(names) - 1})")
    matches = [n for n in names if wanted.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"no port matching {wanted!r}")
    raise SystemExit(f"{wanted!r} matches several ports: {matches}")


def list_ports():
    print("Inputs:")
    for i, name in enumerate(mido.get_input_names()):
        print(f"  {i}: {name}")
    print("Outputs:")
    for i, name in enumerate(mido.get_output_names()):
        print(f"  {i}: {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_port",
                        help="input port (number or name substring)")
    parser.add_argument("--out", dest="out_port",
                        help="output port (number or name substring)")
    parser.add_argument("--base", type=int, default=ZONE_BASE,
                        help="lowest note of the modifier zone (default %(default)s)")
    parser.add_argument("--channel", type=int, default=1, choices=range(1, 17),
                        metavar="1-16", help="output MIDI channel (default %(default)s)")
    args = parser.parse_args(argv)

    if not args.in_port or not args.out_port:
        list_ports()
        parser.exit(message="\nRun again with --in and --out.\n")

    in_name = pick_port(mido.get_input_names(), args.in_port)
    out_name = pick_port(mido.get_output_names(), args.out_port)
    engine = ChordEngine(zone_base=args.base, channel=args.channel - 1)

    with mido.open_input(in_name) as inport, mido.open_output(out_name) as outport:
        print(f"orchid: {in_name} -> {out_name} (Ctrl+C to quit)")
        try:
            for msg in inport:
                for out in engine.process(msg):
                    outport.send(out)
        except KeyboardInterrupt:
            pass
        finally:
            for out in engine.flush():
                outport.send(out)
            print("\nbye")


if __name__ == "__main__":
    main()
