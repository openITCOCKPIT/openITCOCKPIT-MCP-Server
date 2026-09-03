"""Allows ``python -m openitcockpit_mcp`` alongside the ``oitc-mcp`` script."""

from openitcockpit_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
