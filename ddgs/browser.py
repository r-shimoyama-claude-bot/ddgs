"""Playwright browser manager for JavaScript-rendered search engines."""

import atexit
import logging
import threading
from contextlib import suppress
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .exceptions import TimeoutException

logger = logging.getLogger(__name__)

# Stealth JS scripts injected before every page load to avoid bot detection
_STEALTH_SCRIPTS = """
// Hide navigator.webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Add realistic plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ],
});

// Add realistic mimeTypes
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => [
        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
    ],
});

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// Hide automation indicators on chrome object
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };

// Override navigator.languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Fake WebGL vendor/renderer to hide headless
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Google Inc. (NVIDIA)';
    if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1060, OpenGL 4.5)';
    return getParameter.call(this, parameter);
};
"""


class BrowserManager:
    """Manages a shared Playwright browser with per-thread contexts.

    Browser is lazily launched on first use. Contexts are created per-thread
    and reused until the proxy changes. Stealth scripts are injected to avoid
    bot detection.
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Browser | None = None
        self._local = threading.local()
        self._lock = threading.Lock()

    def _ensure_browser(self) -> Browser:
        """Lazily launch the shared browser."""
        if self._browser is None or not self._browser.is_connected():
            with self._lock:
                if self._browser is None or not self._browser.is_connected():
                    if self._playwright is None:
                        self._playwright = sync_playwright().start()
                    self._browser = self._playwright.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-extensions",
                            "--no-sandbox",
                        ],
                    )
        return self._browser

    def _get_context(
        self,
        proxy: str | None = None,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        locale: str | None = None,
    ) -> BrowserContext:
        """Get or create a BrowserContext for the current thread."""
        current_proxy = getattr(self._local, "_proxy", None)
        ctx: BrowserContext | None = getattr(self._local, "_context", None)

        if ctx is not None and current_proxy == proxy:
            return ctx

        if ctx is not None:
            with suppress(Exception):
                ctx.close()

        browser = self._ensure_browser()
        kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 720},
            "locale": locale or "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light",
            "device_scale_factor": 1.0,
            "has_touch": False,
            "java_script_enabled": True,
        }
        if proxy:
            kwargs["proxy"] = {"server": proxy}
        if user_agent:
            kwargs["user_agent"] = user_agent
        if extra_headers:
            kwargs["extra_http_headers"] = extra_headers

        ctx = browser.new_context(**kwargs)

        # Inject stealth scripts before every page load
        ctx.add_init_script(_STEALTH_SCRIPTS)

        self._local._context = ctx
        self._local._proxy = proxy
        return ctx

    def fetch_html(
        self,
        url: str,
        *,
        proxy: str | None = None,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_ms: float = 30_000,
        wait_until: str = "networkidle",
        cookies: dict[str, str] | None = None,
        cookie_domain: str | None = None,
        locale: str | None = None,
    ) -> str | None:
        """Navigate to URL and return fully rendered HTML."""
        page: Page | None = None
        try:
            ctx = self._get_context(
                proxy=proxy, user_agent=user_agent, extra_headers=extra_headers, locale=locale
            )

            if cookies and cookie_domain:
                ctx.add_cookies(
                    [{"name": k, "value": v, "domain": cookie_domain, "path": "/"} for k, v in cookies.items()]
                )

            page = ctx.new_page()
            response = page.goto(url, timeout=timeout_ms, wait_until=wait_until)
            if response is None:
                return None
            if response.status >= 400:
                logger.debug("Playwright: HTTP %d for %s", response.status, url)
                return None
            return page.content()
        except Exception as ex:
            if "timeout" in str(ex).lower():
                raise TimeoutException(ex) from ex
            logger.debug("Playwright fetch failed for %s: %r", url, ex)
            return None
        finally:
            if page is not None and not page.is_closed():
                page.close()

    def close(self) -> None:
        """Shutdown browser and playwright."""
        ctx = getattr(self._local, "_context", None)
        if ctx is not None:
            with suppress(Exception):
                ctx.close()
            self._local._context = None

        if self._browser is not None:
            with suppress(Exception):
                self._browser.close()
            self._browser = None

        if self._playwright is not None:
            with suppress(Exception):
                self._playwright.stop()
            self._playwright = None


_browser_manager = BrowserManager()


def _cleanup() -> None:
    """Atexit handler to close browser on process exit."""
    _browser_manager.close()


atexit.register(_cleanup)
