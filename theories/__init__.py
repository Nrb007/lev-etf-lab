"""Theory packages (SPEC Section 15): each owns its data loader, signals and hypothesis specs.

A package may use ``core.data``, ``core.engine`` and the ledger, but nothing in ``core/engine`` or
``core/judge`` imports from here (only the CLI wiring in ``core/cli.py`` does), so no theory is
built into the asset-agnostic engine and judge (SPEC Section 1.6).
"""
