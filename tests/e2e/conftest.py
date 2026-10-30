"""Navegador real contra el servidor Django con React compilado."""

from contextlib import contextmanager
import os
from pathlib import Path

import pytest


@pytest.fixture
def navegador(live_server, request):
    @contextmanager
    def abrir():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_CHANNEL") or None)
            context = browser.new_context(base_url=live_server.url, locale="es-BO")
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                yield page, browser, live_server.url
            except Exception:
                evidencia = Path("evidencias/e2e")
                evidencia.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(evidencia / f"{request.node.name}.png"), full_page=True)
                context.tracing.stop(path=str(evidencia / f"{request.node.name}.zip"))
                raise
            finally:
                context.close()
                browser.close()

    return abrir
