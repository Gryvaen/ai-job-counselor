"""
Boss Zhipin session management.

Boss detects sustained Playwright/CDP automation and blanks pages. Strategy:
1. Keep a real Chrome window open (visible or headless).
2. Open URLs via native Chrome CLI / CDP /json/new — never page.goto on a live attach.
3. Connect Playwright over CDP only briefly (screenshot / parse / read cookies), then disconnect.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright


LOGIN_COOKIE_NAMES = {"t", "bst"}
CHROME_EXECUTABLE = "/usr/bin/google-chrome-stable"
BOSS_LOGIN_URL = "https://login.zhipin.com/?ka=header-login"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def chrome_profile_dir(state_file: Path) -> Path:
    return state_file.parent / "boss_chrome_profile"


class BossSession:
    """Manages Chrome lifecycle for Boss Zhipin with deferred CDP attachment."""

    def __init__(self, state_file: Path, restore_state: bool = True, fresh_login: bool = False):
        self.state_file = state_file
        self.restore_state = restore_state
        self.fresh_login = fresh_login
        self.profile_dir = chrome_profile_dir(state_file)
        self._playwright = None
        self._chrome_process: subprocess.Popen | None = None
        self._chrome_debug_port: int | None = None
        self._headless = True
        self._login_page_url = BOSS_LOGIN_URL

    @property
    def _cdp_endpoint(self) -> str:
        if not self._chrome_debug_port:
            raise RuntimeError("Chrome CDP port is not ready")
        return f"http://127.0.0.1:{self._chrome_debug_port}"

    async def start(self, headless: bool = True) -> None:
        self._headless = headless or not os.environ.get("DISPLAY")
        if self.fresh_login:
            _wipe_profile_cookies(self.profile_dir)

        self._playwright = await async_playwright().start()
        if not Path(CHROME_EXECUTABLE).exists():
            await self._start_playwright_fallback(headless=headless)
            if self.restore_state:
                await self._restore_cookies()
            return

        await self._ensure_profile_available()
        await self._launch_chrome()
        if self.restore_state:
            cookies = await self._read_cookies()
            if cookies:
                await self._save_cookies(cookies)

    async def close(self) -> None:
        try:
            cookies = await self._read_cookies()
            if cookies:
                await self._save_cookies(cookies)
        except Exception as exc:
            print(f"[scraper] Failed to save cookies before close: {exc}")

        if self._chrome_process:
            try:
                self._chrome_process.terminate()
                self._chrome_process.wait(timeout=5)
            except Exception as exc:
                print(f"[scraper] Failed to terminate Chrome process: {exc}")
            self._chrome_process = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                print(f"[scraper] Failed to stop Playwright: {exc}")

    async def get_page(self) -> Page:
        """Return a Boss page from a short-lived CDP session (valid only inside callback)."""
        async with self._cdp_context() as ctx:
            page = self._find_boss_page(ctx)
            if page:
                return page
            return ctx.pages[-1] if ctx.pages else await ctx.new_page()

    async def goto(
        self,
        page: Page,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ) -> Page:
        """Open URL in Chrome, then attach briefly and return the matching page."""
        await self._open_url(url)
        await asyncio.sleep(1.5 if self._headless else 2.0)
        async with self._cdp_context() as ctx:
            found = await self._wait_for_page(ctx, url, timeout=timeout / 1000)
            try:
                await found.wait_for_load_state(wait_until, timeout=5000)
            except Exception:
                pass
            return found

    async def run_with_page(
        self,
        url: str,
        fn: Callable[[Page], Awaitable],
        *,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ):
        """Open a URL natively, attach CDP briefly, run fn(page), then disconnect."""
        await self._open_url(url)
        await asyncio.sleep(1.5 if self._headless else 2.0)
        async with self._cdp_context() as ctx:
            page = await self._wait_for_page(ctx, url, timeout=timeout / 1000)
            try:
                await page.wait_for_load_state(wait_until, timeout=5000)
            except Exception:
                pass
            return await fn(page)

    async def wait_for_login(
        self,
        screenshot_callback=None,
        login_started_callback=None,
    ) -> None:
        if login_started_callback:
            login_started_callback()

        print("[scraper] Opening Boss Zhipin login page. Please scan the QR code in the browser.")
        print("[scraper] Waiting... The pipeline will continue once login cookies are detected.")

        before_names = {c["name"] for c in await self._read_cookies()}
        await self._clear_cookies()

        await self._open_url(BOSS_LOGIN_URL)
        await asyncio.sleep(2.0)
        self._login_page_url = BOSS_LOGIN_URL

        if screenshot_callback:
            await self._capture_login_screenshot(screenshot_callback)

        ticks = 0
        while True:
            if self._chrome_process and self._chrome_process.poll() is not None:
                raise RuntimeError("Boss Chrome 已关闭，请重新发起 /search 并在弹出的浏览器中完成登录。")

            cookies = await self._read_cookies()
            fresh = [
                c for c in cookies
                if c["name"] in LOGIN_COOKIE_NAMES and c["name"] not in before_names
            ]
            if fresh and ticks >= 1:
                break

            if screenshot_callback and ticks % 2 == 0:
                await self._capture_login_screenshot(screenshot_callback)
            ticks += 1
            await asyncio.sleep(2)

        await self._save_cookies(cookies)
        print("[scraper] Login cookies saved.")

    def has_saved_login(self) -> bool:
        if not self.state_file.exists():
            return False
        try:
            with open(self.state_file) as f:
                cookies = json.load(f)
            return any(c.get("name") in LOGIN_COOKIE_NAMES for c in cookies)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Chrome lifecycle
    # ------------------------------------------------------------------

    async def _launch_chrome(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        last_error = None
        for attempt in range(2):
            if attempt:
                print("[scraper] Retrying Chrome launch after profile cleanup...")
                await self._ensure_profile_available()
            self._chrome_debug_port = _free_port()
            cmd = [
                CHROME_EXECUTABLE,
                f"--remote-debugging-port={self._chrome_debug_port}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
            ]
            if self._headless:
                cmd.extend(["--headless=new", "--disable-gpu"])
            cmd.append("about:blank")
            self._chrome_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                await self._wait_cdp_ready(self._cdp_endpoint)
                return
            except Exception as exc:
                last_error = exc
                if self._chrome_process:
                    self._chrome_process.terminate()
                    self._chrome_process = None
        raise RuntimeError(f"Failed to start Chrome for Boss scraping: {last_error}")

    async def _start_playwright_fallback(self, headless: bool) -> None:
        browser = await self._playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        )
        self._context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        self._browser = browser

    async def _open_url(self, url: str) -> None:
        if self._headless:
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self._cdp_endpoint}/json/new?{quote(url, safe='')}",
                    timeout=15,
                )
                response.raise_for_status()
            return

        subprocess.Popen(
            [
                CHROME_EXECUTABLE,
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @asynccontextmanager
    async def _cdp_context(self):
        browser = await self._playwright.chromium.connect_over_cdp(self._cdp_endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("Chrome CDP connected without a browser context.")
            yield browser.contexts[0]
        finally:
            await browser.close()

    async def _read_cookies(self) -> list[dict]:
        async with self._cdp_context() as ctx:
            return await ctx.cookies()

    async def _clear_cookies(self) -> None:
        async with self._cdp_context() as ctx:
            await ctx.clear_cookies()

    async def _capture_login_screenshot(self, screenshot_callback) -> None:
        for attempt in range(4):
            try:
                async with self._cdp_context() as ctx:
                    page = self._find_login_page(ctx)
                    if not page:
                        await asyncio.sleep(0.75)
                        continue
                    screenshot = await page.screenshot(type="png", full_page=False)
                screenshot_callback(screenshot)
                return
            except Exception as exc:
                if attempt == 3:
                    print(f"[scraper] Failed to capture login screenshot: {exc}")
                await asyncio.sleep(0.75)

    async def _wait_for_page(self, ctx: BrowserContext, url: str, timeout: float = 30.0) -> Page:
        host = urlparse(url).netloc
        path_hint = urlparse(url).path.rstrip("/")
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            page = self._match_page(ctx, host=host, path_hint=path_hint)
            if page:
                return page
            await asyncio.sleep(0.25)
        raise TimeoutError(f"Timed out opening {url} in Chrome")

    def _match_page(self, ctx: BrowserContext, host: str, path_hint: str) -> Page | None:
        for candidate in reversed(ctx.pages):
            candidate_url = candidate.url or ""
            if self._is_blank_page(candidate):
                continue
            if host and host not in candidate_url:
                continue
            if path_hint and path_hint not in urlparse(candidate_url).path.rstrip("/"):
                continue
            return candidate
        return None

    def _find_login_page(self, ctx: BrowserContext) -> Page | None:
        for candidate in reversed(ctx.pages):
            url = candidate.url or ""
            if self._is_blank_page(candidate):
                continue
            if "login.zhipin.com" in url:
                return candidate
        return self._match_page(ctx, host=urlparse(BOSS_LOGIN_URL).netloc, path_hint="")

    def _find_boss_page(self, ctx: BrowserContext) -> Page | None:
        job_pages: list[Page] = []
        other_pages: list[Page] = []
        for candidate in ctx.pages:
            url = candidate.url or ""
            if self._is_blank_page(candidate) or "zhipin.com" not in url:
                continue
            if "login.zhipin.com" in url:
                continue
            if "/web/geek/job" in url:
                job_pages.append(candidate)
            else:
                other_pages.append(candidate)
        if job_pages:
            return job_pages[-1]
        if other_pages:
            return other_pages[-1]
        return None

    @staticmethod
    def _is_blank_page(page: Page) -> bool:
        try:
            url = (page.url or "").strip()
            return not url or url == "about:blank"
        except Exception:
            return True

    async def _restore_cookies(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                cookies = json.load(f)
            if cookies:
                async with self._cdp_context() as ctx:
                    await ctx.add_cookies(cookies)
                print(f"[scraper] Restored {len(cookies)} cookies from {self.state_file}")
        except Exception as e:
            print(f"[scraper] Failed to restore cookies: {e}")

    async def _save_cookies(self, cookies: list[dict]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(cookies, f, indent=2)

    async def _ensure_profile_available(self) -> None:
        if not _profile_in_use(self.profile_dir) and not (self.profile_dir / "SingletonLock").exists():
            return
        print("[scraper] Clearing stale Boss Chrome profile lock...")
        subprocess.run(
            ["pkill", "-f", f"--user-data-dir={self.profile_dir}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        for _ in range(20):
            if not _profile_in_use(self.profile_dir):
                break
            await asyncio.sleep(0.25)
        for path in (
            self.profile_dir / "SingletonLock",
            self.profile_dir / "SingletonSocket",
            self.profile_dir / "SingletonCookie",
        ):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _wait_cdp_ready(self, endpoint: str, timeout: float = 15.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        last_error = None
        async with httpx.AsyncClient() as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._chrome_process and self._chrome_process.poll() is not None:
                    raise RuntimeError("Chrome exited before CDP became ready")
                try:
                    response = await client.get(f"{endpoint}/json/version", timeout=1)
                    if response.status_code == 200:
                        return
                except Exception as exc:
                    last_error = exc
                await asyncio.sleep(0.25)
        raise RuntimeError(f"Failed to connect to Chrome over CDP: {last_error}")


def _profile_in_use(profile_dir: Path) -> bool:
    lock = profile_dir / "SingletonLock"
    if not lock.exists():
        return False
    try:
        target = os.readlink(lock)
        lock_pid = Path(target).name
        return lock_pid.isdigit() and Path(f"/proc/{lock_pid}").exists()
    except Exception:
        return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wipe_profile_cookies(profile_dir: Path) -> None:
    default = profile_dir / "Default"
    if not default.exists():
        return
    print("[scraper] Clearing persisted Boss Chrome cookies for a fresh login...")
    for name in ("Cookies", "Cookies-journal", "Network Persistent State"):
        target = default / name
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[scraper] Could not remove {target.name}: {exc}")
