#!/usr/bin/env python3
"""
Login helper for Boss Zhipin.
Opens a Playwright browser, navigates to login, waits for cookies, then saves them.

Usage:
    python scripts/login_boss.py
"""

import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.session import BOSS_LOGIN_URL, BossSession
from config.settings import settings


async def main():
    parser = argparse.ArgumentParser(description="Open Boss Zhipin login and save cookies.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Clear the dedicated Boss Chrome profile before opening the login page.",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("Boss Zhipin Login Helper")
    print("=" * 50)
    print(f"State file: {settings.boss_state_path}")
    print(f"Chrome profile: {settings.boss_state_path.parent / 'boss_chrome_profile'}")
    print()

    session = BossSession(settings.boss_state_path, fresh_login=args.fresh)
    try:
        await session.start(headless=False, initial_url=BOSS_LOGIN_URL)  # Show browser window
        print("请在弹出的 Boss 浏览器窗口里完成登录。")
        print("登录成功后，不要关闭浏览器，回到这个终端按 Enter 保存登录态。")
        await asyncio.to_thread(input, "已登录后按 Enter 继续...")
        if not await session.save_current_login():
            raise RuntimeError(
                "没有读到 Boss 登录 cookie。请确认是在脚本弹出的 Boss 浏览器窗口中完成登录，"
                "不是在你平时使用的 Chrome 窗口中登录。"
            )
    finally:
        await session.close()

    print("Login cookies saved. You can now run the pipeline.")


if __name__ == "__main__":
    asyncio.run(main())
