"""Single public dispatcher for the current generation and repair runtime."""

import argparse
import importlib
import sys


COMMANDS = {
    "generate": "scripts.generate",
    "codegen": "scripts.codegen",
    "repair": "scripts.repair",
    "judge": "scripts.judge",
    "spatial": "scripts.spatial",
}


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="ReDeck: source-grounded slide generation and unified repair")
    parser.add_argument("command", choices=COMMANDS)
    if not arguments or arguments[0] in {"-h", "--help"}:
        parser.print_help()
        return
    selected = parser.parse_args(arguments[:1])
    return importlib.import_module(COMMANDS[selected.command]).main(arguments[1:])


if __name__ == "__main__":
    main()
