"""network/pairing/token.py birim testleri."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_KOK = Path(__file__).resolve().parents[3]
if str(_KOK) not in sys.path:
    sys.path.insert(0, str(_KOK))

from network.pairing.token import TokenYoneticisi


def test_token_uretim_ve_dogrulama() -> None:
    t = TokenYoneticisi()
    paket = t.token_uret(ttl_saniye=60)
    assert paket.gecerli_mi
    assert t.dogrula(paket.token, paket.parmak_izi)
    assert not t.dogrula("yanlis", paket.parmak_izi)
    assert paket.parmak_izi != paket.token


def test_kod_alti_hane() -> None:
    t = TokenYoneticisi()
    kod = t.kod_uret(6)
    assert len(kod) == 6
    assert kod.isdigit()


def test_ttl() -> None:
    t = TokenYoneticisi()
    paket = t.token_uret(ttl_saniye=1)
    assert not t.ttl_dolmus_mu(paket.son_gecerlilik_unix)
    assert t.ttl_dolmus_mu(time.time() - 1)


if __name__ == "__main__":
    test_token_uretim_ve_dogrulama()
    test_kod_alti_hane()
    test_ttl()
    print("OK test_token")
