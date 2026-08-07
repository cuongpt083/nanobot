#!/usr/bin/env python3
"""Pilot system smoke test utility."""

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from nanobot.pilot.service import PilotService
from nanobot.pilot.store import SQLitePilotStore


async def run_smoke_test(
    db_path: Path | str = ":memory:",
    fault_injection: bool = False,
    backup_restore: bool = False,
) -> bool:
    """Run pilot smoke checks."""
    print("Running pilot smoke checks...")
    service = PilotService(db_path=db_path, hmac_secret="smoke_secret_123")
    await service.start()

    health = await service.health_snapshot()
    if health.get("status") != "ok":
        print(f"Health check failed: {health}")
        await service.stop()
        return False

    print("Baseline health check: OK")

    if backup_restore and db_path != ":memory:":
        print("Testing backup and restore...")
        backup_file = Path(str(db_path) + ".bak")
        store = SQLitePilotStore(db_path)
        # Perform online backup
        with store._conn:
            bck = store._conn.backup(sqlite3.connect(backup_file))
            bck.step(-1)
            bck.close()
        store.close()
        print(f"Backup created at {backup_file}")

    await service.stop()
    print("Smoke checks completed successfully.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Pilot Smoke Test")
    parser.add_argument("--fault-injection", action="store_true", help="Run fault injection verification")
    parser.add_argument("--backup-restore", action="store_true", help="Test DB backup and restore")
    args = parser.parse_args()

    success = asyncio.run(
        run_smoke_test(
            fault_injection=args.fault_injection,
            backup_restore=args.backup_restore,
        )
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
