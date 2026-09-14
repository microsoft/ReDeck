"""Explicit CLI compatibility without retaining a second default repair loop."""

import sys

from redeck_style.cli import main


def run(command, argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    print(f"Compatibility entry point: using redeck {command}; only the current runtime is supported.", file=sys.stderr)
    if "--spatial-only" in arguments:
        arguments.remove("--spatial-only")
        arguments.extend(["--probe-routes", "spatial", "--content-repair", "off"])
    if "--max-turns" in arguments:
        index = arguments.index("--max-turns")
        arguments[index] = "--attempts"
        if command == "generate" and "--repair" not in arguments:
            arguments.append("--repair")
        print("--max-turns now denotes one shared candidate budget, not nested repair loops.", file=sys.stderr)
    if command == "generate":
        if "--html-codegen" in arguments:
            arguments.remove("--html-codegen")
        if "--configs" in arguments:
            index = arguments.index("--configs")
            if arguments[index + 1:index + 2] != ["html_codegen"]:
                raise SystemExit("Historical experiment configs are not supported; use the current generation options")
            del arguments[index:index + 2]
    return main([command, *arguments])
