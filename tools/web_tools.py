"""Investigación web explícita para documentación y aprendizaje de APIs."""
from __future__ import annotations

from urllib.parse import urlparse

from config import settings


def buscar_en_internet(consulta: str, max_resultados: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(consulta, max_results=max(1, min(int(max_resultados), 10))))
        return "\n\n".join(
            f"{i}. {item.get('title', '')}\nURL: {item.get('href', item.get('url', ''))}\n{item.get('body', '')}"
            for i, item in enumerate(results, 1)
        ) or "No se encontraron resultados."
    except Exception as exc:
        return f"Búsqueda web no disponible: {type(exc).__name__}: {exc}"


def leer_documentacion_web(url: str) -> str:
    try:
        import httpx
        from bs4 import BeautifulSoup
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not settings.host_is_public(parsed.hostname):
            return "URL bloqueada: solo se permiten destinos HTTP/HTTPS públicos."
        response = httpx.get(url, follow_redirects=False, timeout=20, headers={"User-Agent": settings.USER_AGENT})
        if response.is_redirect:
            return "URL bloqueada: no se siguen redirecciones automáticamente."
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()
        return " ".join(soup.get_text(" ", strip=True).split())[:6000]
    except Exception as exc:
        return f"No se pudo leer la documentación: {type(exc).__name__}: {exc}"
