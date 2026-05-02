"""Onboard a Flow account from a BitBrowser profile.

This script intentionally never prints ST/AT/cookie/proxy secrets. It supports
the standard two-step onboarding flow:

1. Open a BitBrowser profile and navigate to Flow for manual login.
2. After login, extract the Flow session cookie, de-duplicate by email/ST, and
   add or update the Flow2API token with the profile's bit_browser_id.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FLOW_URL = "https://labs.google/fx/tools/flow"
SESSION_COOKIE = "__Secure-next-auth.session-token"


def mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "<unknown>"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[:1] + "***"
    else:
        masked_name = name[:2] + "***"
    return f"{masked_name}@{domain}"


def bitbrowser_post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"BitBrowser API request failed: {exc}") from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BitBrowser API returned non-JSON response") from exc

    if not result.get("success"):
        raise RuntimeError(result.get("msg") or result.get("message") or "BitBrowser API failed")
    return result


def open_bitbrowser(base_url: str, browser_id: str) -> str:
    result = bitbrowser_post(base_url, "/browser/open", {"id": browser_id})
    ws = (result.get("data") or {}).get("ws")
    if not ws:
        raise RuntimeError("BitBrowser /browser/open response did not include data.ws")
    return ws


async def navigate_flow(ws_url: str, flow_url: str) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        pages = [page for page in context.pages if not page.is_closed()]
        page = next((item for item in pages if not item.url.startswith("chrome://")), None)
        if page is None:
            page = await context.new_page()
        await page.goto(flow_url, wait_until="domcontentloaded", timeout=90_000)
        return {
            "title": await page.title(),
            "url": page.url,
            "tabs": len(context.pages),
        }


async def extract_session_token(ws_url: str, flow_url: str) -> tuple[str, dict[str, Any]]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(ws_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = None
        for candidate in context.pages:
            if "labs.google" in candidate.url or "accounts.google" in candidate.url:
                page = candidate
                break
        if page is None:
            page = context.pages[0] if context.pages else await context.new_page()

        if "labs.google" not in page.url:
            await page.goto(flow_url, wait_until="domcontentloaded", timeout=90_000)
        else:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass

        cookies = await context.cookies("https://labs.google")
        st = next(
            (cookie.get("value") for cookie in cookies if cookie.get("name") == SESSION_COOKIE and cookie.get("value")),
            None,
        )
        info = {
            "title": await page.title(),
            "url": page.url,
            "tabs": len(context.pages),
            "st_len": len(st) if st else 0,
        }
        if not st:
            raise RuntimeError("Flow session cookie was not found. Confirm login and accept any Flow prompts.")
        return st, info


def parse_expires(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


async def bind_token(
    st: str,
    browser_id: str,
    remark: Optional[str],
    image_enabled: bool,
    video_enabled: bool,
) -> dict[str, Any]:
    from src.core.database import Database
    from src.services.flow_client import FlowClient
    from src.services.proxy_manager import ProxyManager
    from src.services.token_manager import TokenManager

    db = Database()
    await db.reload_config_to_memory()

    proxy_manager = ProxyManager(db)
    flow_client = FlowClient(proxy_manager, db=db)
    token_manager = TokenManager(db, flow_client)

    session = await flow_client.st_to_at(st)
    at = session["access_token"]
    user = session.get("user") or {}
    email = user.get("email") or ""
    name = user.get("name") or (email.split("@", 1)[0] if email else "")
    at_expires = parse_expires(session.get("expires"))

    credits = 0
    tier = None
    try:
        credits_result = await flow_client.get_credits(at)
        credits = int(credits_result.get("credits") or 0)
        tier = credits_result.get("userPaygateTier")
    except Exception:
        pass

    existing_by_st = await db.get_token_by_st(st)
    existing_by_email = await db.get_token_by_email(email) if email else None
    existing = existing_by_st or existing_by_email
    token_remark = remark or f"BitBrowser {browser_id}"

    if existing:
        await db.update_token(
            existing.id,
            st=st,
            at=at,
            at_expires=at_expires,
            email=email or existing.email,
            name=name or existing.name,
            remark=token_remark,
            is_active=True,
            credits=credits,
            user_paygate_tier=tier,
            bit_browser_id=browser_id,
            image_enabled=image_enabled,
            video_enabled=video_enabled,
            ban_reason="",
        )
        action = "updated"
        token_id = existing.id
        project_id = existing.current_project_id
    else:
        token = await token_manager.add_token(
            st=st,
            remark=token_remark,
            image_enabled=image_enabled,
            video_enabled=video_enabled,
            image_concurrency=-1,
            video_concurrency=-1,
            bit_browser_id=browser_id,
        )
        action = "added"
        token_id = token.id
        project_id = token.current_project_id
        email = token.email
        credits = token.credits
        tier = token.user_paygate_tier

    return {
        "action": action,
        "token_id": token_id,
        "email": mask_email(email),
        "bit_browser_id": browser_id,
        "credits": credits,
        "user_paygate_tier": tier,
        "project_id_present": bool(project_id),
        "image_enabled": image_enabled,
        "video_enabled": video_enabled,
    }


async def run(args: argparse.Namespace) -> int:
    ws_url = open_bitbrowser(args.base_url, args.browser_id)

    if args.open_login:
        page = await navigate_flow(ws_url, args.flow_url)
        print(json.dumps({"ok": True, "step": "open_login", **page}, ensure_ascii=False))
        if not args.bind:
            return 0

    if args.bind:
        st, page = await extract_session_token(ws_url, args.flow_url)
        result = await bind_token(
            st=st,
            browser_id=args.browser_id,
            remark=args.remark,
            image_enabled=not args.disable_image,
            video_enabled=not args.disable_video,
        )
        print(json.dumps({"ok": True, "step": "bind", "page": page, "result": result}, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": True, "step": "open", "message": "BitBrowser window opened"}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open and bind a Flow account from BitBrowser.")
    parser.add_argument("--browser-id", required=True, help="BitBrowser profile/window id to use.")
    parser.add_argument("--base-url", default="http://127.0.0.1:54345", help="BitBrowser local API base URL.")
    parser.add_argument("--flow-url", default=FLOW_URL, help="Flow page to open before login.")
    parser.add_argument("--remark", default=None, help="Remark stored on the Flow2API token.")
    parser.add_argument("--open-login", action="store_true", help="Open the profile and navigate to Flow.")
    parser.add_argument("--bind", action="store_true", help="Extract session cookie and add/update token.")
    parser.add_argument("--disable-image", action="store_true", help="Disable image generation for this token.")
    parser.add_argument("--disable-video", action="store_true", help="Disable video generation for this token.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.open_login and not args.bind:
        args.open_login = True
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
