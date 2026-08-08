"""
network/http/sunucu.py
----------------------
Telefon web paneli + eşleştirme HTTP API.

Görev:
- static mobile/web/static dosyalarını sunmak
- POST /api/pair ile kod eşleştirme
- GET /api/status ile ONLINE özet
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from core.logger import logger_al

log = logger_al("network.http.sunucu")

_STATIC = Path(__file__).resolve().parents[2] / "mobile" / "web" / "static"

PairHandler = Callable[[str, str], dict[str, Any]]
StatusHandler = Callable[[], dict[str, Any]]


def lan_ip_al() -> str:
    """LAN IPv4 adresi (QR / telefon bağlantısı için)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.4)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


class TelefonHttpSunucu:
    """ThreadingHTTPServer üzerinde telefon paneli."""

    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8741,
        static_dir: Optional[Path] = None,
        pair_handler: Optional[PairHandler] = None,
        status_handler: Optional[StatusHandler] = None,
        ws_port: int = 8742,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.ws_port = int(ws_port)
        self.static_dir = Path(static_dir) if static_dir else _STATIC
        self.pair_handler = pair_handler
        self.status_handler = status_handler
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._calisiyor = False
        self.lan_ip = lan_ip_al()

    @property
    def calisiyor(self) -> bool:
        return self._calisiyor

    @property
    def panel_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/"

    def baslat(self) -> None:
        if self._calisiyor:
            return
        self.lan_ip = lan_ip_al()
        sunucu = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
                log.debug("HTTP " + fmt, *args)

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _json(self, kod: int, veri: dict[str, Any]) -> None:
                ham = json.dumps(veri, ensure_ascii=False).encode("utf-8")
                self.send_response(kod)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self._cors()
                self.send_header("Content-Length", str(len(ham)))
                self.end_headers()
                self.wfile.write(ham)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                yol = urlparse(self.path).path
                if yol == "/api/status":
                    durum = {"online": True, "lan_ip": sunucu.lan_ip, "ws_port": sunucu.ws_port}
                    if sunucu.status_handler:
                        try:
                            durum.update(sunucu.status_handler())
                        except Exception as exc:
                            durum["error"] = str(exc)
                    self._json(200, durum)
                    return
                if yol in {"/", "/index.html"}:
                    self._dosya("index.html", "text/html; charset=utf-8")
                    return
                if yol.startswith("/static/"):
                    self._dosya(yol[len("/static/") :], None)
                    return
                # kök dosyalar
                ad = yol.lstrip("/")
                if ad and ".." not in ad:
                    self._dosya(ad, None)
                    return
                self._json(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                yol = urlparse(self.path).path
                uzunluk = int(self.headers.get("Content-Length") or 0)
                ham = self.rfile.read(max(0, uzunluk)) if uzunluk else b"{}"
                try:
                    veri = json.loads(ham.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._json(400, {"ok": False, "error": "invalid_json"})
                    return
                if yol == "/api/pair":
                    if sunucu.pair_handler is None:
                        self._json(503, {"ok": False, "error": "pair_unavailable"})
                        return
                    kod = str(veri.get("code") or "").strip()
                    ad = str(veri.get("name") or "iPhone").strip() or "iPhone"
                    if not kod:
                        self._json(400, {"ok": False, "error": "code_required"})
                        return
                    try:
                        sonuc = sunucu.pair_handler(kod, ad)
                        self._json(200, {"ok": True, **sonuc})
                    except Exception as exc:
                        self._json(400, {"ok": False, "error": str(exc)})
                    return
                self._json(404, {"ok": False, "error": "not_found"})

            def _dosya(self, ad: str, mime: Optional[str]) -> None:
                hedef = (sunucu.static_dir / ad).resolve()
                try:
                    hedef.relative_to(sunucu.static_dir.resolve())
                except ValueError:
                    self._json(403, {"error": "forbidden"})
                    return
                if not hedef.is_file():
                    self._json(404, {"error": "not_found", "path": ad})
                    return
                if mime is None:
                    if ad.endswith(".html"):
                        mime = "text/html; charset=utf-8"
                    elif ad.endswith(".js"):
                        mime = "application/javascript; charset=utf-8"
                    elif ad.endswith(".css"):
                        mime = "text/css; charset=utf-8"
                    elif ad.endswith(".png"):
                        mime = "image/png"
                    elif ad.endswith(".svg"):
                        mime = "image/svg+xml"
                    elif ad.endswith(".webmanifest"):
                        mime = "application/manifest+json"
                    else:
                        mime = "application/octet-stream"
                data = hedef.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self._cors()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as exc:
            log.warning("HTTP telefon paneli acilamadi (%s:%s): %s", self.host, self.port, exc)
            self._httpd = None
            return

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="whitecore-phone-http",
            daemon=True,
        )
        self._thread.start()
        self._calisiyor = True
        log.info(
            "Telefon HTTP paneli ONLINE: %s (static=%s)",
            self.panel_url,
            self.static_dir,
        )

    def durdur(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception as exc:
                log.warning("HTTP durdurma: %s", exc)
        self._httpd = None
        self._thread = None
        self._calisiyor = False
        log.info("Telefon HTTP paneli durduruldu")

    def ozet(self) -> dict[str, Any]:
        return {
            "running": self._calisiyor,
            "host": self.host,
            "port": self.port,
            "lan_ip": self.lan_ip,
            "panel_url": self.panel_url if self._calisiyor else "",
            "ws_port": self.ws_port,
            "static": str(self.static_dir),
        }


__all__ = ["TelefonHttpSunucu", "lan_ip_al"]
