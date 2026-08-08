"""
sync/chat/senkron.py
--------------------
Sohbet geçmişi senkronizasyonu (host tarafı).

Görev:
- Yerel JSON depoda sohbet kayıtlarını tutmak (takvim stili)
- Uzak mesajları uygulamak / birleştirmek (id + zaman damgası)
- Diff (eksik / yeni kayıtlar) üretmek
- SohbetSenkronu arayüzünü (gonder / cek) doldurmak
- protokol CHAT_SYNC yükü üretmek / işlemek (WS sunucu ack ile uyumlu)
- dry_run / bellek içi modda ağ ve disk olmadan test edilebilir olmak
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.exceptions import WhiteCoreError
from core.logger import audit_yaz, logger_al
from network.websocket.protokol import MesajTipi, WsMesaj, mesaj_olustur
from sync.arayuzler import SohbetSenkronu

log = logger_al("sync.chat.senkron")

_KOK = Path(__file__).resolve().parents[2]
_VARSAYILAN_DEPO = _KOK / "data" / "sync" / "chat" / "messages.json"
_DEPO_SURUM = 1


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _parse_iso(metin: str) -> Optional[datetime]:
    s = (metin or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def varsayilan_depo_yolu() -> Path:
    return _VARSAYILAN_DEPO


def mesaj_normalize(ham: dict[str, Any]) -> dict[str, Any]:
    """
    Gelen sözlüğü kanonik sohbet kaydına çevirir.

    Kabul edilen anahtarlar (TR / EN):
      id/mesaj_id, role/rol, content/icerik, timestamp/zaman/ts,
      session_id/oturum_id, device_id/cihaz_id, meta
    """
    if not isinstance(ham, dict):
        raise WhiteCoreError(
            "Sohbet kaydi sozluk olmali",
            kod="SYNC_0001",
            modul="sync.chat",
        )
    mid = ham.get("id") or ham.get("mesaj_id") or uuid4().hex
    rol = ham.get("role") or ham.get("rol") or "user"
    icerik = ham.get("content") if "content" in ham else ham.get("icerik")
    if icerik is None:
        icerik = ""
    zaman = (
        ham.get("timestamp")
        or ham.get("zaman")
        or ham.get("ts")
        or _utc_iso()
    )
    oturum = ham.get("session_id") or ham.get("oturum_id")
    cihaz = ham.get("device_id") or ham.get("cihaz_id")
    meta = ham.get("meta") if isinstance(ham.get("meta"), dict) else {}
    kayit: dict[str, Any] = {
        "id": str(mid),
        "role": str(rol),
        "content": str(icerik),
        "timestamp": str(zaman),
        "meta": dict(meta),
    }
    if oturum is not None:
        kayit["session_id"] = str(oturum)
    if cihaz is not None:
        kayit["device_id"] = str(cihaz)
    return kayit


def mesajlari_normalize(mesajlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mesaj_normalize(m) for m in mesajlar if isinstance(m, dict)]


def _zaman_anahtar(kayit: dict[str, Any]) -> str:
    return str(kayit.get("timestamp") or "")


def _daha_yeni_mi(aday: dict[str, Any], mevcut: dict[str, Any]) -> bool:
    """Aday mevcuttan daha yeni mi? (eşitlikte aday kazanır — uzak uygulama)."""
    t_aday = _parse_iso(_zaman_anahtar(aday))
    t_mevcut = _parse_iso(_zaman_anahtar(mevcut))
    if t_aday is None and t_mevcut is None:
        return True
    if t_aday is None:
        return False
    if t_mevcut is None:
        return True
    return t_aday >= t_mevcut


def birlestir(
    yerel: list[dict[str, Any]],
    uzak: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    İki mesaj listesini id üzerinden birleştirir.

    Aynı id'de daha yeni timestamp kazanır; sonuç timestamp + id sırası.
    """
    harita: dict[str, dict[str, Any]] = {}
    for m in mesajlari_normalize(yerel):
        harita[m["id"]] = m
    for m in mesajlari_normalize(uzak):
        eski = harita.get(m["id"])
        if eski is None or _daha_yeni_mi(m, eski):
            harita[m["id"]] = m
    return sorted(
        harita.values(),
        key=lambda x: (_zaman_anahtar(x), x["id"]),
    )


def fark(
    yerel: list[dict[str, Any]],
    uzak: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    İki küme arasındaki fark.

    - only_local: yerelde var, uzakta yok
    - only_remote: uzakta var, yerelde yok
    - newer_local / newer_remote: her iki tarafta var, timestamp farklı
    """
    y_map = {m["id"]: m for m in mesajlari_normalize(yerel)}
    u_map = {m["id"]: m for m in mesajlari_normalize(uzak)}
    only_local: list[dict[str, Any]] = []
    only_remote: list[dict[str, Any]] = []
    newer_local: list[dict[str, Any]] = []
    newer_remote: list[dict[str, Any]] = []

    for mid, ym in y_map.items():
        um = u_map.get(mid)
        if um is None:
            only_local.append(ym)
        elif _zaman_anahtar(ym) != _zaman_anahtar(um):
            if _daha_yeni_mi(ym, um) and not _daha_yeni_mi(um, ym):
                newer_local.append(ym)
            elif _daha_yeni_mi(um, ym) and not _daha_yeni_mi(ym, um):
                newer_remote.append(um)
            else:
                # eşit zaman — yok say
                pass

    for mid, um in u_map.items():
        if mid not in y_map:
            only_remote.append(um)

    return {
        "only_local": only_local,
        "only_remote": only_remote,
        "newer_local": newer_local,
        "newer_remote": newer_remote,
    }


def _depo_yukle(yol: Path) -> dict[str, Any]:
    """JSON depo paketini yükler; yoksa boş iskelet."""
    bos = {
        "version": _DEPO_SURUM,
        "updated": _utc_iso(),
        "messages": [],
        "cursors": {},
    }
    if not yol.is_file():
        return bos
    try:
        ham = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return bos
    if isinstance(ham, list):
        return {
            "version": _DEPO_SURUM,
            "updated": _utc_iso(),
            "messages": mesajlari_normalize([x for x in ham if isinstance(x, dict)]),
            "cursors": {},
        }
    if not isinstance(ham, dict):
        return bos
    mesajlar = ham.get("messages") or ham.get("mesajlar") or []
    if not isinstance(mesajlar, list):
        mesajlar = []
    cursors = ham.get("cursors") or ham.get("imlecler") or {}
    if not isinstance(cursors, dict):
        cursors = {}
    return {
        "version": int(ham.get("version") or _DEPO_SURUM),
        "updated": str(ham.get("updated") or _utc_iso()),
        "messages": mesajlari_normalize([x for x in mesajlar if isinstance(x, dict)]),
        "cursors": {str(k): str(v) for k, v in cursors.items()},
    }


def _depo_kaydet(yol: Path, paket: dict[str, Any]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    cikti = {
        "version": int(paket.get("version") or _DEPO_SURUM),
        "updated": _utc_iso(),
        "messages": list(paket.get("messages") or []),
        "cursors": dict(paket.get("cursors") or {}),
    }
    yol.write_text(
        json.dumps(cikti, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@dataclass
class SenkronOzet:
    """Son senkron işlem özeti."""

    eklenen: int = 0
    guncellenen: int = 0
    atlanan: int = 0
    toplam: int = 0
    motor: str = "json"
    dry_run: bool = False
    cihaz_id: Optional[str] = None
    detay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.eklenen,
            "updated": self.guncellenen,
            "skipped": self.atlanan,
            "total": self.toplam,
            "engine": self.motor,
            "dry_run": self.dry_run,
            "device_id": self.cihaz_id,
            "detail": dict(self.detay),
        }


class SohbetSenkron(SohbetSenkronu, ModulTabani):
    """
    Host sohbet senkron uygulaması.

    Motorlar:
      - dry_run: disk yazmaz, bellek içi
      - memory / sahte: bellek (zorla_sahte)
      - json: data/sync/chat/messages.json
    """

    ad = "sync.chat"
    surum = "0.1.0"
    aciklama = "Sohbet gecmisi senkronu (JSON / dry_run)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        depo_yolu: Optional[Union[str, Path]] = None,
    ) -> None:
        ModulTabani.__init__(self)
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(
            self.ayarlar.al("mobile.features.chat_sync", True)
        )
        yol = depo_yolu
        if yol is None:
            yol = self.ayarlar.al("sync.chat.store_path", None)
        self.depo_yolu = (
            Path(yol).expanduser() if yol else varsayilan_depo_yolu()
        )

        self._mesajlar: list[dict[str, Any]] = []
        self._cursors: dict[str, str] = {}
        self._giden: dict[str, list[dict[str, Any]]] = {}  # cihaz → kuyruk
        self._motor = self._motor_sec()
        self._yuklendi = False

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise WhiteCoreError(
                "Sohbet senkronu config ile kapali (mobile.features.chat_sync=false)",
                kod="SYNC_0002",
                modul=self.ad,
            )
        self._motor = self._motor_sec()
        self._yukle()
        self._calisiyor = True
        audit_yaz(
            "chat_sync.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "store": str(self.depo_yolu),
                "count": len(self._mesajlar),
            },
        )
        log.info(
            "Sohbet senkronu basladi (motor=%s, kayit=%s)",
            self._motor,
            len(self._mesajlar),
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()
        self._calisiyor = False
        audit_yaz(
            "chat_sync.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "count": len(self._mesajlar)},
        )
        log.info("Sohbet senkronu durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ API

    @property
    def motor(self) -> str:
        return self._motor

    def listele(
        self,
        *,
        cihaz_id: Optional[str] = None,
        son_sonra: Optional[str] = None,
        oturum_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Depodaki mesajları filtreleyerek döner."""
        self._ensure_yuklu()
        sonuc: list[dict[str, Any]] = []
        esik = _parse_iso(son_sonra) if son_sonra else None
        for m in self._mesajlar:
            # cihaz etiketi yoksa paylaşımlı kabul; farklı cihazı atla
            if cihaz_id is not None:
                mid = m.get("device_id")
                if mid is not None and mid != cihaz_id:
                    continue
            if oturum_id and m.get("session_id") != oturum_id:
                continue
            if esik is not None:
                mt = _parse_iso(_zaman_anahtar(m))
                if mt is None or mt <= esik:
                    continue
            sonuc.append(dict(m))
        return sonuc

    def kaydet(
        self,
        mesajlar: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> SenkronOzet:
        """Yerel depoya mesaj yazar (upsert)."""
        return self.uygula(mesajlar, cihaz_id=cihaz_id, kaynak="local")

    def uygula(
        self,
        mesajlar: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
        kaynak: str = "remote",
    ) -> SenkronOzet:
        """
        Mesaj listesini depoya uygular (merge / upsert).

        dry_run: bellek güncellenir ama disk yazılmaz.
        """
        self._ensure_yuklu()
        gelen = mesajlari_normalize(mesajlar)
        if cihaz_id:
            for m in gelen:
                m.setdefault("device_id", cihaz_id)

        onceki = {m["id"]: m for m in self._mesajlar}
        eklenen = 0
        guncellenen = 0
        atlanan = 0

        for m in gelen:
            eski = onceki.get(m["id"])
            if eski is None:
                onceki[m["id"]] = m
                eklenen += 1
            elif _daha_yeni_mi(m, eski) and _zaman_anahtar(m) != _zaman_anahtar(eski):
                onceki[m["id"]] = m
                guncellenen += 1
            elif eski != m and _zaman_anahtar(m) == _zaman_anahtar(eski):
                # aynı zaman, içerik/meta güncellemesi
                if (
                    eski.get("content") != m.get("content")
                    or eski.get("role") != m.get("role")
                    or eski.get("meta") != m.get("meta")
                ):
                    onceki[m["id"]] = m
                    guncellenen += 1
                else:
                    atlanan += 1
            else:
                atlanan += 1

        self._mesajlar = sorted(
            onceki.values(),
            key=lambda x: (_zaman_anahtar(x), x["id"]),
        )
        if cihaz_id and gelen:
            # imleç: en son uygulanan timestamp
            son = max((_zaman_anahtar(m) for m in gelen), default="")
            if son:
                self._cursors[cihaz_id] = son

        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()

        ozet = SenkronOzet(
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=atlanan,
            toplam=len(self._mesajlar),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=cihaz_id,
            detay={"source": kaynak, "incoming": len(gelen)},
        )
        audit_yaz(
            "chat_sync.apply",
            modul=self.ad,
            detay=ozet.to_dict(),
        )
        log.debug(
            "Senkron uygula: +%s ~%s skip=%s (kaynak=%s)",
            eklenen,
            guncellenen,
            atlanan,
            kaynak,
        )
        return ozet

    def fark_hesapla(
        self,
        uzak: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
        son_sonra: Optional[str] = None,
    ) -> dict[str, Any]:
        """Yerel depo ile uzak liste arasındaki fark."""
        yerel = self.listele(cihaz_id=cihaz_id, son_sonra=son_sonra)
        d = fark(yerel, uzak)
        return {
            "device_id": cihaz_id,
            "after": son_sonra,
            "engine": self._motor,
            "dry_run": self.dry_run,
            **d,
            "counts": {k: len(v) for k, v in d.items()},
        }

    def birlestir_uzak(
        self,
        uzak: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> SenkronOzet:
        """Uzak listeyi yerel ile birleştirip depoya yazar."""
        self._ensure_yuklu()
        birlesik = birlestir(self._mesajlar, uzak)
        # birleşik kümeden yalnızca değişenleri uygula yerine tam set
        onceki_ids = {m["id"]: m for m in self._mesajlar}
        eklenen = 0
        guncellenen = 0
        for m in birlesik:
            eski = onceki_ids.get(m["id"])
            if eski is None:
                eklenen += 1
            elif eski != m:
                guncellenen += 1
        self._mesajlar = birlesik
        if cihaz_id and uzak:
            son = max((_zaman_anahtar(m) for m in mesajlari_normalize(uzak)), default="")
            if son:
                self._cursors[cihaz_id] = son
        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()
        ozet = SenkronOzet(
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=0,
            toplam=len(self._mesajlar),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=cihaz_id,
            detay={"source": "merge"},
        )
        audit_yaz("chat_sync.merge", modul=self.ad, detay=ozet.to_dict())
        return ozet

    async def gonder(
        self,
        cihaz_id: str,
        mesajlar: list[dict[str, Any]],
    ) -> None:
        """
        Sohbet kayıtlarını hedef cihaza / depoya gönderir.

        dry_run: giden kuyruğa yazar, disk yok.
        json: depoya kaydeder + cihaz kuyruğuna koyar (üst katman WS ile iletir).
        """
        if not self._calisiyor:
            raise WhiteCoreError(
                "Sohbet senkronu calismiyor; once baslat() cagirin",
                kod="SYNC_0003",
                modul=self.ad,
            )
        cid = str(cihaz_id or "").strip()
        if not cid:
            raise WhiteCoreError(
                "cihaz_id gerekli",
                kod="SYNC_0004",
                modul=self.ad,
            )
        norm = mesajlari_normalize(mesajlar)
        for m in norm:
            m.setdefault("device_id", cid)
        self.uygula(norm, cihaz_id=cid, kaynak="outbound")
        kuyruk = self._giden.setdefault(cid, [])
        kuyruk.extend(dict(m) for m in norm)
        audit_yaz(
            "chat_sync.send",
            modul=self.ad,
            detay={
                "device_id": cid,
                "count": len(norm),
                "engine": self._motor,
                "dry_run": self.dry_run,
            },
        )

    async def cek(
        self,
        cihaz_id: str,
        son_sonra: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Eksik sohbet kayıtlarını çeker (son_sonra sonrası)."""
        if not self._calisiyor:
            raise WhiteCoreError(
                "Sohbet senkronu calismiyor; once baslat() cagirin",
                kod="SYNC_0003",
                modul=self.ad,
            )
        cid = str(cihaz_id or "").strip()
        esik = son_sonra
        if not esik and cid:
            esik = self._cursors.get(cid)
        return self.listele(cihaz_id=None, son_sonra=esik)

    def giden_cek(self, cihaz_id: str) -> list[dict[str, Any]]:
        """Cihaz giden kuyruğunu alıp temizler (test / dry_run / WS köprüsü)."""
        kuyruk = self._giden.pop(str(cihaz_id), [])
        return list(kuyruk)

    # ------------------------------------------------------------------ protokol

    def chat_sync_mesaji(
        self,
        mesajlar: Optional[list[dict[str, Any]]] = None,
        *,
        cihaz_id: Optional[str] = None,
        islem: str = "push",
        son_sonra: Optional[str] = None,
    ) -> WsMesaj:
        """
        protokol.MesajTipi.CHAT_SYNC zarfı üretir.

        payload: {op, messages, after?}
        """
        if mesajlar is None:
            mesajlar = self.listele(cihaz_id=cihaz_id, son_sonra=son_sonra)
        yuk: dict[str, Any] = {
            "op": islem,
            "messages": mesajlari_normalize(mesajlar),
        }
        if son_sonra:
            yuk["after"] = son_sonra
        return mesaj_olustur(MesajTipi.CHAT_SYNC, yuk, cihaz_id=cihaz_id)

    def chat_sync_isle(
        self,
        mesaj: Union[WsMesaj, dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Gelen CHAT_SYNC mesajını uygular; sunucu ack detayı ile uyumlu özet döner.

        op:
          - push / apply: uzak mesajları uygula
          - pull / diff: yerel fark özeti (uygulama yok)
          - merge: birleştir
        """
        if isinstance(mesaj, WsMesaj):
            if mesaj.tip is not MesajTipi.CHAT_SYNC:
                raise WhiteCoreError(
                    f"Beklenen tip chat_sync, gelen: {mesaj.tip.value}",
                    kod="SYNC_0005",
                    modul=self.ad,
                )
            yuk = dict(mesaj.yuk)
            cid = cihaz_id or mesaj.cihaz_id
        else:
            yuk = dict(mesaj)
            cid = cihaz_id or yuk.get("device_id") or yuk.get("cihaz_id")

        op = str(yuk.get("op") or yuk.get("islem") or "push").lower()
        ham_liste = yuk.get("messages") or yuk.get("mesajlar") or []
        if not isinstance(ham_liste, list):
            ham_liste = []
        after = yuk.get("after") or yuk.get("son_sonra")

        if op in {"pull", "diff", "cek"}:
            d = self.fark_hesapla(ham_liste, cihaz_id=str(cid) if cid else None, son_sonra=after)
            return {
                "ok": True,
                "type": MesajTipi.CHAT_SYNC.value,
                "op": "diff",
                "device_id": cid,
                **d,
            }

        if op == "merge":
            ozet = self.birlestir_uzak(ham_liste, cihaz_id=str(cid) if cid else None)
            return {
                "ok": True,
                "type": MesajTipi.CHAT_SYNC.value,
                "op": "merge",
                **ozet.to_dict(),
            }

        # varsayılan: push / apply
        ozet = self.uygula(
            ham_liste,
            cihaz_id=str(cid) if cid else None,
            kaynak="chat_sync",
        )
        return {
            "ok": True,
            "type": MesajTipi.CHAT_SYNC.value,
            "op": "apply",
            **ozet.to_dict(),
        }

    def ozet(self) -> dict[str, Any]:
        self._ensure_yuklu()
        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "store": str(self.depo_yolu),
            "count": len(self._mesajlar),
            "devices_queued": {k: len(v) for k, v in self._giden.items()},
            "cursors": dict(self._cursors),
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "json"

    def _ensure_yuklu(self) -> None:
        if not self._yuklendi:
            self._yukle()

    def _yukle(self) -> None:
        if self._motor in {"dry_run", "sahte"}:
            if not self._yuklendi:
                self._mesajlar = []
                self._cursors = {}
            self._yuklendi = True
            return
        paket = _depo_yukle(self.depo_yolu)
        self._mesajlar = list(paket.get("messages") or [])
        self._cursors = dict(paket.get("cursors") or {})
        self._yuklendi = True

    def _kaydet_disk(self) -> None:
        _depo_kaydet(
            self.depo_yolu,
            {
                "version": _DEPO_SURUM,
                "messages": self._mesajlar,
                "cursors": self._cursors,
            },
        )


__all__ = [
    "SohbetSenkron",
    "SenkronOzet",
    "varsayilan_depo_yolu",
    "mesaj_normalize",
    "mesajlari_normalize",
    "birlestir",
    "fark",
]
