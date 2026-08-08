"""config/env.py birim testi."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from config.env import env_anahtar_yaz, env_yukle


def test_env_yukle(tmp_path: Path | None = None) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        yol = Path(d) / ".env"
        yol.write_text(
            "# yorum\nOPENAI_API_KEY=sk-test-123\nEXPORT FOO=bar\n",
            encoding="utf-8",
        )
        once = os.environ.pop("OPENAI_API_KEY", None)
        once_foo = os.environ.pop("FOO", None)
        try:
            assert env_yukle(yol) == yol
            assert os.environ.get("OPENAI_API_KEY") == "sk-test-123"
            assert os.environ.get("FOO") == "bar"
            # ezmez
            os.environ["OPENAI_API_KEY"] = "sk-keep"
            env_yukle(yol)
            assert os.environ["OPENAI_API_KEY"] == "sk-keep"
        finally:
            if once is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = once
            if once_foo is None:
                os.environ.pop("FOO", None)
            else:
                os.environ["FOO"] = once_foo


def test_env_anahtar_yaz() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        yol = Path(d) / ".env"
        yol.write_text("OPENAI_API_KEY=eski\nDIGER=1\n", encoding="utf-8")
        once = os.environ.pop("OPENAI_API_KEY", None)
        try:
            env_anahtar_yaz("OPENAI_API_KEY", "sk-yeni", yol=yol)
            metin = yol.read_text(encoding="utf-8")
            assert "sk-yeni" in metin
            assert "DIGER=1" in metin
            assert os.environ["OPENAI_API_KEY"] == "sk-yeni"
        finally:
            if once is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = once


if __name__ == "__main__":
    test_env_yukle()
    test_env_anahtar_yaz()
    print("OK test_env")
