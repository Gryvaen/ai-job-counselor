#!/usr/bin/env python3
"""
Login helper for Boss Zhipin.
Opens a Playwright browser, navigates to login, waits for cookies, then saves them.

Usage:
    python scripts/login_boss.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.session import BossSession
from config.settings import settings


async def main():
    print("=" * 50)
    print("Boss Zhipin Login Helper")
    print("=" * 50)
    print(f"State file: {settings.boss_state_path}")
    print()

    session = BossSession(settings.boss_state_path)
    await session.start(headless=False)  # Show browser window
    await session.wait_for_login()
    await session.close()

    print("Login cookies saved. You can now run the pipeline.")


if __name__ == "__main__":
    asyncio.run(main())
