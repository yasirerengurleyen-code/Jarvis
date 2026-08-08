"""Yerel indirme sitesi: python website/serve.py"""

from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

KOK = Path(__file__).resolve().parent
PORT = 8787


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(KOK), **kwargs)


def main() -> int:
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/"
        print(f"WhiteCore indirme sitesi: {url}")
        print("Durdurmak icin Ctrl+C")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDurduruldu")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
