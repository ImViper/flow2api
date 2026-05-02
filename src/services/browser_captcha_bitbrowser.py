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
        self._custom_lock = asyncio.Lock()
        self._resident_pages: Dict[str, BitBrowserResidentPage] = {}
        self._custom_pages: Dict[str, Dict[str, Any]] = {}
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
            await self._close_orphan_recaptcha_pages()
            self._initialized = True
            debug_logger.log_info(f"[BitBrowserCaptcha] 已连接 BitBrowser CDP: browser_id={self._browser_id}")

    async def close(self, disconnect_only: bool = False):
        async with self._connect_lock:
            async with self._resident_lock:
                pages = [item.page for item in self._resident_pages.values() if item.page]
                self._resident_pages.clear()
                self._project_affinity.clear()
            async with self._custom_lock:
                custom_pages = [
                    item.get("page")
                    for item in self._custom_pages.values()
                    if isinstance(item, dict) and item.get("page")
                ]
                self._custom_pages.clear()
            pages.extend(custom_pages)
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
        max_pages = max(1, int(limit or self._max_resident_pages()))
        for project_id in list(project_ids or [])[:max_pages]:
            slot_id, info = await self._ensure_resident_page(str(project_id or "").strip())
            if slot_id and info:
                warmed.append(slot_id)
        return warmed

    def _max_resident_pages(self) -> int:
        try:
            return max(1, int(config.personal_max_resident_tabs or 1))
        except Exception:
            return 1

    def _idle_resident_ttl_seconds(self) -> int:
        try:
            return max(0, int(config.personal_idle_tab_ttl_seconds or 0))
        except Exception:
            return 0

    def _resident_key(self, project_id: str, bit_browser_id: Optional[str] = None) -> str:
        browser_id = self._select_browser_id(bit_browser_id)
        return f"{browser_id}::{str(project_id or '').strip()}"

    def _drop_affinity_for_slot_locked(self, slot_id: str):
        stale_keys = [
            key for key, mapped_slot_id in self._project_affinity.items()
            if mapped_slot_id == slot_id
        ]
        for key in stale_keys:
            self._project_affinity.pop(key, None)

    def _select_reusable_resident_locked(self) -> tuple[Optional[str], Optional[BitBrowserResidentPage]]:
        candidates = [
            (slot_id, info)
            for slot_id, info in self._resident_pages.items()
            if info and info.page
        ]
        if not candidates:
            return None, None

        ready_idle = [
            item for item in candidates
            if item[1].recaptcha_ready and not item[1].solve_lock.locked()
        ]
        ready_any = [item for item in candidates if item[1].recaptcha_ready]
        idle_any = [item for item in candidates if not item[1].solve_lock.locked()]
        pool = ready_idle or ready_any or idle_any or candidates
        return min(pool, key=lambda item: item[1].last_used_at)

    async def _close_resident_page_quietly(self, info: Optional[BitBrowserResidentPage]):
        if not info or not info.page:
            return
        try:
            await info.page.close()
        except Exception:
            pass

    async def _close_orphan_recaptcha_pages(self):
        if not self._context:
            return
        target_url = "https://labs.google/fx/api/auth/providers"
        closed_count = 0
        for page in list(self._context.pages):
            try:
                if page.is_closed():
                    continue
                if (page.url or "").rstrip("/") != target_url.rstrip("/"):
                    continue
                await page.close()
                closed_count += 1
            except Exception:
                continue
        if closed_count:
            debug_logger.log_info(
                f"[BitBrowserCaptcha] 已清理旧的孤儿打码标签页: count={closed_count}"
            )

    async def _prune_idle_resident_pages(self):
        ttl_seconds = self._idle_resident_ttl_seconds()
        if ttl_seconds <= 0:
            return

        now_value = time.time()
        stale_pages: list[BitBrowserResidentPage] = []
        async with self._resident_lock:
            for slot_id, info in list(self._resident_pages.items()):
                if not info or info.solve_lock.locked():
                    continue
                if (now_value - info.last_used_at) < ttl_seconds:
                    continue
                stale_pages.append(info)
                self._resident_pages.pop(slot_id, None)
                self._drop_affinity_for_slot_locked(slot_id)

        for info in stale_pages:
            await self._close_resident_page_quietly(info)
        if stale_pages:
            debug_logger.log_info(
                f"[BitBrowserCaptcha] 已回收空闲常驻标签页: count={len(stale_pages)}, ttl={ttl_seconds}s"
            )

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
        await self._prune_idle_resident_pages()
        affinity_key = self._resident_key(project_id, bit_browser_id)
        stale_pages: list[BitBrowserResidentPage] = []
        async with self._resident_lock:
            slot_id = self._project_affinity.get(affinity_key)
            existing = self._resident_pages.get(slot_id) if slot_id else None
            if existing and existing.page and existing.recaptcha_ready:
                return slot_id, existing
            if slot_id and existing:
                stale_pages.append(existing)
                self._resident_pages.pop(slot_id, None)
                self._drop_affinity_for_slot_locked(slot_id)

            max_pages = self._max_resident_pages()
            if len(self._resident_pages) >= max_pages:
                reusable_slot, reusable_info = self._select_reusable_resident_locked()
                if reusable_slot and reusable_info:
                    self._project_affinity[affinity_key] = reusable_slot
                    reusable_info.project_id = project_id
                    debug_logger.log_info(
                        f"[BitBrowserCaptcha] 常驻标签页达到上限({max_pages})，复用 slot={reusable_slot}"
                    )
                    return reusable_slot, reusable_info

            self._slot_seq += 1
            slot_id = f"bit-{self._slot_seq}"
            self._project_affinity[affinity_key] = slot_id

        for info in stale_pages:
            await self._close_resident_page_quietly(info)

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
                html = """<html><head><title>flow2api recaptcha</title></head><body></body></html>"""
                await route.fulfill(status=200, content_type="text/html", body=html)
            elif any(domain in route.request.url for domain in ("google.com", "gstatic.com", "recaptcha.net")):
                await route.continue_()
            else:
                await route.abort()

        await page.route("**/*", handle_route)
        await page.goto(page_url, wait_until="domcontentloaded", timeout=10000)
        if not await self._inject_recaptcha_script_if_needed(
            page,
            website_key,
            enterprise=True,
            timeout_ms=45000,
        ):
            raise RuntimeError("reCAPTCHA enterprise script did not become ready")

    async def _inject_recaptcha_script_if_needed(
        self,
        page,
        website_key: str,
        enterprise: bool = True,
        timeout_ms: int = 15000,
    ) -> bool:
        wait_expression = (
            "typeof grecaptcha !== 'undefined' && typeof grecaptcha.enterprise !== 'undefined' && "
            "typeof grecaptcha.enterprise.execute === 'function'"
        ) if enterprise else (
            "typeof grecaptcha !== 'undefined' && typeof grecaptcha.execute === 'function'"
        )
        try:
            await page.wait_for_function(wait_expression, timeout=2500)
            return True
        except Exception:
            pass

        script_path = "recaptcha/enterprise.js" if enterprise else "recaptcha/api.js"
        primary_url = f"https://www.google.com/{script_path}?render={website_key}"
        secondary_url = f"https://www.recaptcha.net/{script_path}?render={website_key}"
        try:
            await page.evaluate(
                """
                ([primaryUrl, secondaryUrl]) => {
                    const existing = Array.from(document.scripts || []).some((script) => {
                        const src = script && script.src || "";
                        return src.includes("/recaptcha/");
                    });
                    if (existing) return;
                    const urls = [primaryUrl, secondaryUrl];
                    const loadScript = (index) => {
                        if (index >= urls.length) return;
                        const script = document.createElement("script");
                        script.src = urls[index];
                        script.async = true;
                        script.onerror = () => loadScript(index + 1);
                        document.head.appendChild(script);
                    };
                    loadScript(0);
                }
                """,
                [primary_url, secondary_url],
            )
            await page.wait_for_function(wait_expression, timeout=timeout_ms)
            return True
        except Exception as e:
            debug_logger.log_warning(
                f"[BitBrowserCaptcha] reCAPTCHA script not ready: {type(e).__name__}: {str(e)[:200]}"
            )
            return False

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
        if not await self._inject_recaptcha_script_if_needed(page, self.website_key, enterprise=True):
            return None
        return await asyncio.wait_for(
            page.evaluate(
                """
                ([websiteKey, actionName]) => {
                    return new Promise((resolve, reject) => {
                        const timeout = setTimeout(() => reject(new Error('timeout')), 45000);
                        try {
                            grecaptcha.enterprise.ready(() => {
                                grecaptcha.enterprise.execute(websiteKey, {action: actionName})
                                    .then((token) => { clearTimeout(timeout); resolve(token); })
                                    .catch((err) => { clearTimeout(timeout); reject(err); });
                            });
                        } catch (err) {
                            clearTimeout(timeout);
                            reject(err);
                        }
                    });
                }
                """,
                [self.website_key, action or "IMAGE_GENERATION"],
            ),
            timeout=55,
        )

    async def _execute_custom_recaptcha(
        self,
        page,
        website_key: str,
        action: str,
        enterprise: bool = False,
    ) -> Optional[str]:
        if not await self._inject_recaptcha_script_if_needed(page, website_key, enterprise=enterprise):
            return None
        execute_target = "grecaptcha.enterprise.execute" if enterprise else "grecaptcha.execute"
        ready_target = "grecaptcha.enterprise.ready" if enterprise else "grecaptcha.ready"
        return await asyncio.wait_for(
            page.evaluate(
                f"""
                ([websiteKey, actionName]) => {{
                    return new Promise((resolve, reject) => {{
                        const timeout = setTimeout(() => reject(new Error('timeout')), 25000);
                        try {{
                            {ready_target}(() => {{
                                {execute_target}(websiteKey, {{action: actionName}})
                                .then((token) => {{ clearTimeout(timeout); resolve(token); }})
                                .catch((err) => {{ clearTimeout(timeout); reject(err); }});
                            }});
                        }} catch (err) {{
                            clearTimeout(timeout);
                            reject(err);
                        }}
                    }});
                }}
                """,
                [website_key, action or "homepage"],
            ),
            timeout=30,
        )

    async def _verify_score_in_page(self, page, token: str, verify_url: str) -> Dict[str, Any]:
        _ = token
        _ = verify_url
        started_at = time.time()
        timeout_seconds = 25.0
        refresh_clicked = False
        last_snapshot: Dict[str, Any] = {}
        try:
            timeout_seconds = float(getattr(config, "browser_score_dom_wait_seconds", 25) or 25)
        except Exception:
            pass

        while (time.time() - started_at) < timeout_seconds:
            try:
                result = await page.evaluate(
                    """
                    () => {
                        const bodyText = ((document.body && document.body.innerText) || "")
                            .replace(/\\u00a0/g, " ")
                            .replace(/\\r/g, "");
                        const patterns = [
                            { source: "current_score", regex: /Your score is:\\s*([01](?:\\.\\d+)?)/i },
                            { source: "selected_score", regex: /Selected Score Test:[\\s\\S]{0,400}?Score:\\s*([01](?:\\.\\d+)?)/i },
                            { source: "history_score", regex: /(?:^|\\n)\\s*Score:\\s*([01](?:\\.\\d+)?)\\s*;/i },
                        ];
                        let score = null;
                        let source = "";
                        for (const item of patterns) {
                            const match = bodyText.match(item.regex);
                            if (!match) continue;
                            const parsed = Number(match[1]);
                            if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) {
                                score = parsed;
                                source = item.source;
                                break;
                            }
                        }
                        const uaMatch = bodyText.match(/Current User Agent:\\s*([^\\n]+)/i);
                        const ipMatch = bodyText.match(/Current IP Address:\\s*([^\\n]+)/i);
                        return {
                            score,
                            source,
                            raw_text: bodyText.slice(0, 4000),
                            current_user_agent: uaMatch ? uaMatch[1].trim() : "",
                            current_ip_address: ipMatch ? ipMatch[1].trim() : "",
                            title: document.title || "",
                            url: location.href || "",
                        };
                    }
                    """
                )
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}

            if isinstance(result, dict):
                last_snapshot = result
                score = result.get("score")
                if isinstance(score, (int, float)):
                    elapsed_ms = int((time.time() - started_at) * 1000)
                    return {
                        "verify_mode": "browser_page_dom",
                        "verify_elapsed_ms": elapsed_ms,
                        "verify_http_status": None,
                        "verify_result": {
                            "success": True,
                            "score": score,
                            "source": result.get("source") or "antcpt_dom",
                            "raw_text": result.get("raw_text") or "",
                            "current_user_agent": result.get("current_user_agent") or "",
                            "current_ip_address": result.get("current_ip_address") or "",
                            "page_title": result.get("title") or "",
                            "page_url": result.get("url") or "",
                        },
                    }

            if not refresh_clicked and (time.time() - started_at) >= 2:
                refresh_clicked = True
                try:
                    await page.evaluate(
                        """
                        () => {
                            const nodes = Array.from(
                                document.querySelectorAll('button, input[type="button"], input[type="submit"], a')
                            );
                            const target = nodes.find((node) => {
                                const text = (node.innerText || node.textContent || node.value || "").trim();
                                return /Refresh score now!?/i.test(text);
                            });
                            if (target) {
                                target.click();
                                return true;
                            }
                            return false;
                        }
                        """
                    )
                except Exception:
                    pass
            await asyncio.sleep(0.5)

        elapsed_ms = int((time.time() - started_at) * 1000)
        return {
            "verify_mode": "browser_page_dom",
            "verify_elapsed_ms": elapsed_ms,
            "verify_http_status": None,
            "verify_result": {
                "success": False,
                "score": None,
                "source": "antcpt_dom_timeout",
                "raw_text": last_snapshot.get("raw_text") or "",
                "current_user_agent": last_snapshot.get("current_user_agent") or "",
                "current_ip_address": last_snapshot.get("current_ip_address") or "",
                "page_title": last_snapshot.get("title") or "",
                "page_url": last_snapshot.get("url") or "",
                "error": last_snapshot.get("error") or "score not found in page",
            },
        }

    async def get_custom_token(
        self,
        website_url: str,
        website_key: str,
        action: str = "homepage",
        enterprise: bool = False,
    ) -> Optional[str]:
        payload = await self._get_custom_payload(
            website_url=website_url,
            website_key=website_key,
            action=action,
            enterprise=enterprise,
            verify_url=None,
        )
        if isinstance(payload, dict):
            return payload.get("token")
        return None

    async def get_custom_score(
        self,
        website_url: str,
        website_key: str,
        verify_url: str,
        action: str = "homepage",
        enterprise: bool = False,
    ) -> Dict[str, Any]:
        payload = await self._get_custom_payload(
            website_url=website_url,
            website_key=website_key,
            action=action,
            enterprise=enterprise,
            verify_url=verify_url,
        )
        return payload if isinstance(payload, dict) else {}

    async def _get_custom_payload(
        self,
        website_url: str,
        website_key: str,
        action: str,
        enterprise: bool,
        verify_url: Optional[str],
    ) -> Dict[str, Any]:
        await self.initialize()
        cache_key = f"{website_url}|{website_key}|{1 if enterprise else 0}"
        token_started_at = time.time()
        async with self._custom_lock:
            custom_info = self._custom_pages.get(cache_key)
            page = custom_info.get("page") if isinstance(custom_info, dict) else None
            try:
                if page is None or page.is_closed():
                    page = await self._context.new_page()
                    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                    await page.goto(website_url, wait_until="domcontentloaded", timeout=30000)
                    custom_info = {
                        "page": page,
                        "created_at": time.time(),
                        "recaptcha_ready": False,
                        "warmed_up": False,
                    }
                    self._custom_pages[cache_key] = custom_info

                try:
                    await page.bring_to_front()
                    await page.mouse.move(320, 220)
                    await page.mouse.move(520, 320, steps=12)
                    await page.mouse.wheel(0, 240)
                    await page.evaluate(
                        """
                        () => {
                            try {
                                window.focus();
                                window.dispatchEvent(new Event("focus"));
                                document.dispatchEvent(new MouseEvent("mousemove", {
                                    bubbles: true,
                                    clientX: Math.max(32, Math.floor((window.innerWidth || 1280) * 0.4)),
                                    clientY: Math.max(32, Math.floor((window.innerHeight || 720) * 0.35))
                                }));
                                window.scrollTo(0, Math.min(280, document.body?.scrollHeight || 280));
                            } catch (e) {}
                        }
                        """
                    )
                except Exception:
                    pass

                if not custom_info.get("recaptcha_ready"):
                    custom_info["recaptcha_ready"] = await self._inject_recaptcha_script_if_needed(
                        page,
                        website_key,
                        enterprise=enterprise,
                    )
                    if not custom_info["recaptcha_ready"]:
                        raise RuntimeError("custom reCAPTCHA not ready")

                if not custom_info.get("warmed_up"):
                    try:
                        warmup_seconds = float(getattr(config, "browser_score_test_warmup_seconds", 12) or 12)
                    except Exception:
                        warmup_seconds = 12.0
                    if warmup_seconds > 0:
                        debug_logger.log_info(
                            f"[BitBrowserCaptcha] custom score page warmup {warmup_seconds:.1f}s: {website_url}"
                        )
                        await asyncio.sleep(warmup_seconds)
                    custom_info["warmed_up"] = True
                else:
                    try:
                        settle_seconds = float(getattr(config, "browser_score_test_settle_seconds", 2.5) or 2.5)
                    except Exception:
                        settle_seconds = 2.5
                    if settle_seconds > 0:
                        await asyncio.sleep(settle_seconds)

                token = await self._execute_custom_recaptcha(page, website_key, action, enterprise=enterprise)
                if not token:
                    raise RuntimeError("custom reCAPTCHA returned empty token")
                fingerprint = await self._capture_page_fingerprint(page)
                self._remember_fingerprint(fingerprint)
                token_elapsed_ms = int((time.time() - token_started_at) * 1000)

                payload: Dict[str, Any] = {
                    "token": token,
                    "token_elapsed_ms": token_elapsed_ms,
                    "fingerprint": fingerprint,
                }
                if verify_url:
                    payload.update(await self._verify_score_in_page(page, token, verify_url))
                return payload
            except Exception as e:
                debug_logger.log_warning(
                    f"[BitBrowserCaptcha] custom score/token failed: {type(e).__name__}: {str(e)[:200]}"
                )
                stale_info = self._custom_pages.pop(cache_key, None)
                stale_page = stale_info.get("page") if isinstance(stale_info, dict) else page
                if stale_page:
                    try:
                        await stale_page.close()
                    except Exception:
                        pass
                return {}

    async def refresh_session_token(self, project_id: str, bit_browser_id: Optional[str] = None) -> Optional[str]:
        credentials = await self.refresh_session_credentials(project_id, bit_browser_id=bit_browser_id)
        if credentials and credentials.get("st"):
            return str(credentials["st"])

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

    async def refresh_session_credentials(self, project_id: str, bit_browser_id: Optional[str] = None) -> Optional[dict]:
        await self.initialize(bit_browser_id=bit_browser_id)
        page = None
        try:
            page = await self._context.new_page()
            target = "https://labs.google/fx/tools/flow"
            if project_id:
                target = f"{target}/project/{project_id}"
            await page.goto(target, wait_until="commit", timeout=30000)
            await page.wait_for_timeout(3000)
            session = await page.evaluate("""
                async () => {
                    const result = { ok: false, status: 0, json: null, text: "", error: "" };
                    try {
                        const response = await fetch('/fx/api/auth/session', { credentials: 'include' });
                        result.status = response.status;
                        const text = await response.text();
                        result.text = text.slice(0, 500);
                        try { result.json = JSON.parse(text); } catch (e) {}
                        result.ok = response.ok;
                    } catch (e) {
                        result.error = String(e && e.message || e);
                    }
                    return result;
                }
            """)
            payload = session.get("json") if isinstance(session, dict) else None
            if not isinstance(payload, dict) or not payload.get("access_token"):
                debug_logger.log_warning(f"[BitBrowserCaptcha] browser session refresh failed: {session}")
                return None

            cookies = await self._context.cookies()
            st = None
            for cookie in cookies:
                if cookie.get("name") == "__Secure-next-auth.session-token" and cookie.get("value"):
                    st = str(cookie["value"])
                    break
            payload["st"] = st
            return payload
        except Exception as e:
            debug_logger.log_warning(f"[BitBrowserCaptcha] refresh browser session credentials failed: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
