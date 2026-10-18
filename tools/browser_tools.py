"""Automatización controlada de navegador con Playwright."""
from __future__ import annotations

import json
from urllib.parse import urlparse
from rich.prompt import Confirm
from config import settings
from core.self_coder import confirmar, confirmation_allowed


def automatizar_navegador(url: str, acciones: str = "[]") -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "URL bloqueada: solo se permiten direcciones HTTP/HTTPS válidas."
    if not settings.host_is_public(parsed.hostname or ""):
        return "URL bloqueada: no se permiten destinos locales o redes privadas."
    try:
        steps = json.loads(acciones) if isinstance(acciones, str) else acciones
        if not isinstance(steps, list) or len(steps) > 20:
            return "Acciones inválidas: usa una lista de máximo 20 pasos."
        mutating = [step for step in steps if isinstance(step, dict) and step.get("action") in {"fill", "click"}]
        if mutating and not confirmation_allowed():
            return "Automatización cancelada: las acciones mutables requieren una sesión de consola."
        if mutating and not confirmar(f"¿Autorizas {len(mutating)} acción(es) que pueden modificar una página en {url}?"):
            return "Automatización cancelada: requiere autorización explícita."
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            def guard_request(route):
                request_url = urlparse(route.request.url)
                if request_url.scheme in {"http", "https"} and (
                    not request_url.hostname or not settings.host_is_public(request_url.hostname)
                ):
                    route.abort()
                    return
                route.continue_()
            page.route("**/*", guard_request)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            output = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                action, selector = step.get("action"), step.get("selector", "")
                if action == "fill" and selector:
                    page.locator(selector).fill(str(step.get("value", "")))
                elif action == "click" and selector:
                    page.locator(selector).click()
                elif action == "read":
                    output.append(page.locator(selector).inner_text() if selector else page.locator("body").inner_text())
                elif action == "screenshot":
                    path = settings.DATA_DIR / "screenshots" / "browser_actual.png"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=path, full_page=True)
                    output.append(f"Captura guardada en {path}")
            if not output:
                output.append(page.title() + "\n" + page.locator("body").inner_text()[:6000])
            browser.close()
            return "\n\n".join(output)
    except ImportError:
        return "Playwright está instalado pero falta Chromium: ejecuta `playwright install chromium`."
    except Exception as exc:
        return f"Automatización del navegador falló: {type(exc).__name__}: {exc}"
