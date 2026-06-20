"""
Boss Zhipin session management — Playwright browser lifecycle + cookie persistence.
"""

import json
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class BossSession:
    """Manages Playwright browser session with cookie-based login persistence."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright = None

    async def start(self, headless: bool = True) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        await self._restore_cookies()

    async def close(self) -> None:
        if self._context:
            cookies = await self._context.cookies()
            await self._save_cookies(cookies)
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def get_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Browser not started. Call start() first.")
        return await self._context.new_page()

    async def wait_for_login(self) -> None:
        """Wait for user to complete login in the browser."""
        page = await self.get_page()
        print("[scraper] Navigate to Boss Zhipin login page. Please complete login manually.")
        print("[scraper] Waiting... Will proceed once cookies are detected.")

        await page.goto("https://www.zhipin.com/web/user/safe/login")
        while True:
            cookies = await page.context.cookies()
            has_login_cookie = any(c["name"] in ("t", "bst") for c in cookies)
            if has_login_cookie:
                break
            await page.wait_for_timeout(2000)

        await self._save_cookies(cookies)
        print("[scraper] Login cookies saved.")

    async def _restore_cookies(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                cookies = json.load(f)
            if cookies:
                await self._context.add_cookies(cookies)
                print(f"[scraper] Restored {len(cookies)} cookies from {self.state_file}")
        except Exception as e:
            print(f"[scraper] Failed to restore cookies: {e}")

    async def _save_cookies(self, cookies: list[dict]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(cookies, f, indent=2)
