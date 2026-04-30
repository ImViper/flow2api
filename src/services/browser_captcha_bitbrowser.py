"""BitBrowser-backed reCAPTCHA service.

This mode reuses a BitBrowser profile/window and connects Playwright through
Chrome DevTools Protocol. It keeps Flow's captcha fingerprint aligned with the
BitBrowser profile instead of launching a separate local browser.
"""
import asyncio
import time
from typing import Any, Dict, Iterable, Optional

import httpx

from ..core.config import config
from ..core.logger import debug_logger

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - handled at runtime with a clear error
    async_playwright = None


class BitBrowserResidentPage:
    def __init__(self, page, slot_id: str, project_id: str):
        self.page = page
        self.slot_id = slot_id
        self.project_id = project_id
        self.recaptcha_ready = False
        self.created_at = time.time()
        self.last_used_at = time.time()
        self.use_count = 0
        self.fingerprint: Optional[Dict[str, Any]] = None
        self.solve_lock = asyncio.Lock()


class BrowserCaptchaService:
    """Browser captcha service using BitBrowser profile CDP."""

    _instance: Optional["BrowserCaptchaService"] = None
    _instances: Dict[str, "BrowserCaptchaService"] = {}
    _lock = asyncio.Lock()

    def __init__(self, db=None, browser_id_override: Optional[str] = None):
        self.db = db
        self._browser_id_override = (browser_id_override or "").strip()
        self.website_key = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
        self._base_url = ""
        self._browser_id = ""
        self._close_on_shutdown = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._ws_url = ""
        self._initialized = False
        self._connect_lock = asyncio.Lock()
        self._resident_lock = asyncio.Lock()
        self._resident_pages: Dict[str, BitBrowserResidentPage] = {}
        self._project_affinity: Dict[str, str] = {}
        self._slot_seq = 0
        self._last_fingerprint: Optional[Dict[str, Any]] = None
        self._refresh_config()

    @classmethod
    async def get_instance(cls, db=None, bit_browser_id: Optional[str] = None) -> "BrowserCaptchaService":
        browser_id = (bit_browser_id or "").strip()
        if not browser_id:
            if cls._instance is None:
                async with cls._lock:
                    if cls._instance is None:
                        cls._instance = cls(db)
            return cls._instance

        async with cls._lock:
            instance = cls._instances.get(browser_id)
            if instance is None:
                instance = cls(db, browser_id_override=browser_id)
                cls._instances[browser_id] = instance
            return instance

    @classmethod
    async def reload_all_instances(cls):
        instances = []
        if cls._instance is not None:
            instances.append(cls._instance)
        instances.extend(cls._instances.values())
        for instance in instances:
            await instance.reload_config()

    @classmethod
    async def close_all_instances(cls):
        instances = []
        if cls._instance is not None:
            instances.append(cls._instance)
        instances.extend(cls._instances.values())
        seen = set()
        for instance in instances:
            instance_id = id(instance)
            if instance_id in seen:
                continue
            seen.add(instance_id)
            await instance.close()
        cls._instance = None
        cls._instances.clear()

    def _refresh_config(self):
        self._base_url = (config.bit_browser_base_url or "http://127.0.0.1:54345").strip().rstrip("/")
        self._browser_id = self._browser_id_override or (config.bit_browser_id or "").strip()
        self._close_on_shutdown = bool(config.bit_browser_close_on_shutdown)

    def _select_browser_id(self, bit_browser_id: Optional[str] = None) -> str:
        return (bit_browser_id or self._browser_id or "").strip()

    async def reload_config(self):
        old_base_url = self._base_url
        old_browser_id = self._browser_id
        self._refresh_config()
        if old_base_url != self._base_url or old_browser_id != self._browser_id:
            await self.close(disconnect_only=True)
        debug_logger.log_info(
            f"[BitBrowserCaptcha] 配置已热更新: base_url={self._base_url}, browser_id={self._browser_id or '<empty>'}"
        )

    def _check_available(self, bit_browser_id: Optional[str] = None):
        if async_playwright is None:
            raise RuntimeError("playwright 未安装，请运行: pip install playwright")
        if not self._base_url.startswith(("http://", "https://")):
            raise RuntimeError("BitBrowser 本地 API 地址格式错误")
        if not self._select_browser_id(bit_browser_id):
            raise RuntimeError("BitBrowser 浏览器窗口 ID 未配置")

    async def _bit_api_post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0), trust_env=False) as client:
                response = await client.post(url, json=payload)
        except Exception as e:
            raise RuntimeError(f"BitBrowser API 请求失败: {e}") from e

        text = response.text or ""
        if response.status_code >= 400:
            raise RuntimeError(f"BitBrowser API HTTP {response.status_code}: {text[:200]}")
        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(f"BitBrowser API 返回非 JSON: {text[:200]}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"BitBrowser API 返回格式错误: {data!r}")
        if data.get("success") is False:
            raise RuntimeError(data.get("msg") or data.get("message") or f"BitBrowser API 调用失败: {data}")
        return data

    async def _open_bitbrowser(self, bit_browser_id: Optional[str] = None) -> str:
        browser_id = self._select_browser_id(bit_browser_id)
        payload = await self._bit_api_post("/browser/open", {"id": browser_id})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        ws_url = data.get("ws")
        if not isinstance(ws_url, str) or not ws_url.strip():
            raise RuntimeError(f"BitBrowser /browser/open 返回缺少 data.ws: {payload}")
        return ws_url.strip()

    async def _close_bitbrowser(self, bit_browser_id: Optional[str] = None):
        browser_id = self._select_browser_id(bit_browser_id)
        if not browser_id:
            return
        try:
            await self._bit_api_post("/browser/close", {"id": browser_id})
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 关闭 BitBrowser 窗口失败: {e}")

    async def initialize(self, bit_browser_id: Optional[str] = None):
        self._check_available(bit_browser_id)
        target_browser_id = self._select_browser_id(bit_browser_id)
        if (
            self._initialized
            and self._browser
            and self._context
            and target_browser_id != self._browser_id
        ):
            await self.close(disconnect_only=True)
            self._browser_id = target_browser_id
        if self._initialized and self._browser and self._context:
            return
        async with self._connect_lock:
            if self._initialized and self._browser and self._context:
                return
            self._browser_id = target_browser_id
            self._ws_url = await self._open_bitbrowser(self._browser_id)
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(self._ws_url)
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = await self._browser.new_context()
            self._initialized = True
            debug_logger.log_info(f"[BitBrowserCaptcha] 已连接 BitBrowser CDP: browser_id={self._browser_id}")

    async def close(self, disconnect_only: bool = False):
        async with self._connect_lock:
            async with self._resident_lock:
                pages = [item.page for item in self._resident_pages.values() if item.page]
                self._resident_pages.clear()
                self._project_affinity.clear()
            for page in pages:
                try:
                    await page.close()
                except Exception:
                    pass
            # Do not call browser.close() here: with CDP-attached BitBrowser that
            # may close the real profile window. Stopping Playwright is enough to
            # drop our automation connection.
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            self._playwright = None
            self._browser = None
            self._context = None
            self._initialized = False
            self._ws_url = ""
        if self._close_on_shutdown and not disconnect_only:
            await self._close_bitbrowser()

    async def open_login_window(self):
        await self.initialize()
        page = await self._context.new_page()
        await page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=30000)
        print("请在 BitBrowser 窗口中完成 Google 登录，登录后可在管理页添加/刷新账号。")

    async def warmup_resident_tabs(self, project_ids: Iterable[str], limit: Optional[int] = None) -> list[str]:
        await self.initialize()
        warmed: list[str] = []
        max_pages = max(1, int(limit or config.personal_max_resident_tabs or 1))
        for project_id in list(project_ids or [])[:max_pages]:
            slot_id, info = await self._ensure_resident_page(str(project_id or "").strip())
            if slot_id and info:
                warmed.append(slot_id)
        return warmed

    def _resident_key(self, project_id: str, bit_browser_id: Optional[str] = None) -> str:
        browser_id = self._select_browser_id(bit_browser_id)
        return f"{browser_id}::{str(project_id or '').strip()}"

    async def stop_resident_mode(self, project_id: str, bit_browser_id: Optional[str] = None):
        normalized_project = self._resident_key(project_id, bit_browser_id)
        async with self._resident_lock:
            slot_id = self._project_affinity.pop(normalized_project, None)
            info = self._resident_pages.pop(slot_id, None) if slot_id else None
        if info and info.page:
            try:
                await info.page.close()
            except Exception:
                pass

    async def report_flow_error(
        self,
        project_id: str,
        error_reason: str = "",
        error_message: str = "",
        bit_browser_id: Optional[str] = None,
    ):
        debug_logger.log_warning(
            f"[BitBrowserCaptcha] Flow 请求失败，重建关联打码页: project={project_id}, reason={error_reason or error_message}"
        )
        await self.stop_resident_mode(project_id, bit_browser_id=bit_browser_id)

    async def _ensure_resident_page(
        self,
        project_id: str,
        bit_browser_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[BitBrowserResidentPage]]:
        if not project_id:
            return None, None
        await self.initialize(bit_browser_id=bit_browser_id)
        affinity_key = self._resident_key(project_id, bit_browser_id)
        async with self._resident_lock:
            slot_id = self._project_affinity.get(affinity_key)
            existing = self._resident_pages.get(slot_id) if slot_id else None
            if existing and existing.page and existing.recaptcha_ready:
                return slot_id, existing
            self._slot_seq += 1
            slot_id = f"bit-{self._slot_seq}"
            self._project_affinity[affinity_key] = slot_id

        info = await self._create_resident_page(slot_id, project_id)
        if not info:
            async with self._resident_lock:
                self._project_affinity.pop(affinity_key, None)
            return None, None
        async with self._resident_lock:
            self._resident_pages[slot_id] = info
        return slot_id, info

    async def _create_resident_page(self, slot_id: str, project_id: str) -> Optional[BitBrowserResidentPage]:
        page = None
        try:
            page = await self._context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            await self._load_recaptcha_page(page)
            info = BitBrowserResidentPage(page, slot_id, project_id)
            info.recaptcha_ready = True
            info.fingerprint = await self._capture_page_fingerprint(page)
            self._remember_fingerprint(info.fingerprint)
            return info
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 创建常驻打码页失败: {type(e).__name__}: {str(e)[:200]}")
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            return None

    async def _load_recaptcha_page(self, page):
        page_url = "https://labs.google/fx/api/auth/providers"
        website_key = self.website_key

        async def handle_route(route):
            request_url = route.request.url.rstrip("/")
            if request_url == page_url.rstrip("/"):
                html = f"""<html><head><script>
                const script = document.createElement('script');
                script.src = 'https://www.google.com/recaptcha/enterprise.js?render={website_key}';
                script.async = true;
                document.head.appendChild(script);
                </script></head><body></body></html>"""
                await route.fulfill(status=200, content_type="text/html", body=html)
            elif any(domain in route.request.url for domain in ("google.com", "gstatic.com", "recaptcha.net")):
                await route.continue_()
            else:
                await route.abort()

        await page.route("**/*", handle_route)
        await page.goto(page_url, wait_until="load", timeout=20000)
        await page.wait_for_function(
            "typeof grecaptcha !== 'undefined' && grecaptcha.enterprise && typeof grecaptcha.enterprise.ready === 'function'",
            timeout=15000,
        )

    async def _capture_page_fingerprint(self, page) -> Optional[Dict[str, Any]]:
        try:
            fingerprint = await page.evaluate("""
                () => {
                    const uaData = navigator.userAgentData || null;
                    let secChUa = "";
                    let secChUaMobile = "";
                    let secChUaPlatform = "";
                    if (uaData) {
                        if (Array.isArray(uaData.brands) && uaData.brands.length > 0) {
                            secChUa = uaData.brands.map((item) => `"${item.brand}";v="${item.version}"`).join(", ");
                        }
                        secChUaMobile = uaData.mobile ? "?1" : "?0";
                        if (uaData.platform) secChUaPlatform = `"${uaData.platform}"`;
                    }
                    return {
                        user_agent: navigator.userAgent || "",
                        accept_language: navigator.language || "",
                        sec_ch_ua: secChUa,
                        sec_ch_ua_mobile: secChUaMobile,
                        sec_ch_ua_platform: secChUaPlatform,
                        source: "bitbrowser"
                    };
                }
            """)
            return fingerprint if isinstance(fingerprint, dict) else None
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 提取指纹失败: {e}")
            return None

    def _remember_fingerprint(self, fingerprint: Optional[Dict[str, Any]]):
        self._last_fingerprint = dict(fingerprint) if isinstance(fingerprint, dict) and fingerprint else None

    def get_last_fingerprint(self) -> Optional[Dict[str, Any]]:
        return dict(self._last_fingerprint) if self._last_fingerprint else None

    async def get_token(
        self,
        project_id: str,
        action: str = "IMAGE_GENERATION",
        bit_browser_id: Optional[str] = None,
    ) -> Optional[str]:
        slot_id, info = await self._ensure_resident_page(project_id, bit_browser_id=bit_browser_id)
        if not slot_id or not info:
            return await self._get_token_once(action, bit_browser_id=bit_browser_id)
        try:
            async with info.solve_lock:
                token = await self._execute_recaptcha(info.page, action)
            if token:
                info.last_used_at = time.time()
                info.use_count += 1
                if not info.fingerprint:
                    info.fingerprint = await self._capture_page_fingerprint(info.page)
                self._remember_fingerprint(info.fingerprint)
                return token
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 常驻页打码失败，改用临时页: {e}")
            await self.stop_resident_mode(project_id, bit_browser_id=bit_browser_id)
        return await self._get_token_once(action, bit_browser_id=bit_browser_id)

    async def _get_token_once(self, action: str, bit_browser_id: Optional[str] = None) -> Optional[str]:
        await self.initialize(bit_browser_id=bit_browser_id)
        page = None
        try:
            page = await self._context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            await self._load_recaptcha_page(page)
            fingerprint = await self._capture_page_fingerprint(page)
            token = await self._execute_recaptcha(page, action)
            if token:
                self._remember_fingerprint(fingerprint)
            return token
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 临时页打码失败: {type(e).__name__}: {str(e)[:200]}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _execute_recaptcha(self, page, action: str) -> Optional[str]:
        return await asyncio.wait_for(
            page.evaluate(
                f"""
                (actionName) => {{
                    return new Promise((resolve, reject) => {{
                        const timeout = setTimeout(() => reject(new Error('timeout')), 25000);
                        grecaptcha.enterprise.ready(() => {{
                            grecaptcha.enterprise.execute('{self.website_key}', {{action: actionName}})
                                .then((token) => {{ clearTimeout(timeout); resolve(token); }})
                                .catch((err) => {{ clearTimeout(timeout); reject(err); }});
                        }});
                    }});
                }}
                """,
                action or "IMAGE_GENERATION",
            ),
            timeout=30,
        )

    async def refresh_session_token(self, project_id: str, bit_browser_id: Optional[str] = None) -> Optional[str]:
        await self.initialize(bit_browser_id=bit_browser_id)
        page = None
        try:
            page = await self._context.new_page()
            target = "https://labs.google/fx/tools/flow"
            if project_id:
                target = f"{target}/project/{project_id}"
            await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            cookies = await self._context.cookies()
            for cookie in cookies:
                if cookie.get("name") == "__Secure-next-auth.session-token" and cookie.get("value"):
                    return str(cookie["value"])
            return await page.evaluate("""
                () => {
                    const found = document.cookie.split(';').map(v => v.trim())
                        .find(v => v.startsWith('__Secure-next-auth.session-token='));
                    return found ? decodeURIComponent(found.split('=').slice(1).join('=')) : null;
                }
            """)
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] 刷新 ST 失败: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
