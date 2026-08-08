"""
sync/notifications/bildirim.py
------------------------------
Çapraz cihaz bildirim köprüsü (host tarafı).

Görev:
- Yerel JSON depoda bildirim kayıtlarını tutmak
- BildirimSenkronu arayüzünü (ilet) doldurmak
- Cihaz giden kuyruğu (WS üst katmanı iletir)
- protokol NOTIFICATION yükü üretmek / işlemek (WS sunucu ack ile uyumlu)
- dry_run / bellek içi modda ağ ve disk olmadan test edilebilir olmak
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.exceptions import WhiteCoreError
from core.logger import audit_yaz, logger_al
from network.websocket.protokol import MesajTipi, WsMesaj, mesaj_olustur
from sync.arayuzler import BildirimSenkronu

log = logger_al("sync.notifications.bildirim")

_KOK = Path(__file__).resolve().parents[2]
_VARSAYILAN_DEPO = _KOK / "data" / "sync" / "notifications" / "notifications.json"
_DEPO_SURUM = 1
_VARSAYILAN_MAX_GOVDE = 8 * 1024  # 8 KiB metin


class BildirimDurumu(str, Enum):
    """Bildirim yaşam döngüsü."""

    BEKLIYOR = "pending"
    KUYRUKTA = "queued"
    ILETILDI = "delivered"
    OKUNDU = "read"
    BASARISIZ = "failed"
    IPTAL = "cancelled"


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def varsayilan_depo_yolu() -> Path:
    return _VARSAYILAN_DEPO


def bildirim_normalize(ham: dict[str, Any]) -> dict[str, Any]:
    """
    Gelen sözlüğü kanonik bildirim kaydına çevirir.

    Kabul (TR / EN):
      id/bildirim_id, title/baslik, body/govde, status/durum,
      timestamp/zaman/ts, device_id/cihaz_id, data/veri, meta, priority
    """
    if not isinstance(ham, dict):
        raise WhiteCoreError(
            "Bildirim kaydi sozluk olmali",
            kod="SYNC_0030",
            modul="sync.notifications",
        )
    nid = ham.get("id") or ham.get("bildirim_id") or uuid4().hex
    baslik = ham.get("title") if "title" in ham else ham.get("baslik")
    if baslik is None:
        baslik = ""
    govde = ham.get("body") if "body" in ham else ham.get("govde")
    if govde is None:
        govde = ""
    durum_ham = ham.get("status") or ham.get("durum") or BildirimDurumu.BEKLIYOR.value
    try:
        durum = BildirimDurumu(str(durum_ham).lower()).value
    except ValueError:
        durum = BildirimDurumu.BEKLIYOR.value
    zaman = (
        ham.get("timestamp")
        or ham.get("zaman")
        or ham.get("ts")
        or _utc_iso()
    )
    veri = ham.get("data") if "data" in ham else ham.get("veri")
    if not isinstance(veri, dict):
        veri = {}
    meta = ham.get("meta") if isinstance(ham.get("meta"), dict) else {}
    oncelik = ham.get("priority") or ham.get("oncelik") or "normal"
    kayit: dict[str, Any] = {
        "id": str(nid),
        "title": str(baslik),
        "body": str(govde),
        "status": durum,
        "timestamp": str(zaman),
        "priority": str(oncelik),
        "data": dict(veri),
        "meta": dict(meta),
    }
    cihaz = ham.get("device_id") or ham.get("cihaz_id")
    if cihaz is not None:
        kayit["device_id"] = str(cihaz)
    kaynak = ham.get("source") or ham.get("kaynak")
    if kaynak is not None:
        kayit["source"] = str(kaynak)
    return kayit


def _depo_yukle(yol: Path) -> dict[str, Any]:
    bos = {
        "version": _DEPO_SURUM,
        "updated": _utc_iso(),
        "notifications": [],
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
            "notifications": [
                bildirim_normalize(x) for x in ham if isinstance(x, dict)
            ],
        }
    if not isinstance(ham, dict):
        return bos
    liste = ham.get("notifications") or ham.get("bildirimler") or []
    if not isinstance(liste, list):
        liste = []
    return {
        "version": int(ham.get("version") or _DEPO_SURUM),
        "updated": str(ham.get("updated") or _utc_iso()),
        "notifications": [
            bildirim_normalize(x) for x in liste if isinstance(x, dict)
        ],
    }


def _depo_kaydet(yol: Path, paket: dict[str, Any]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    cikti = {
        "version": int(paket.get("version") or _DEPO_SURUM),
        "updated": _utc_iso(),
        "notifications": list(paket.get("notifications") or []),
    }
    yol.write_text(
        json.dumps(cikti, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@dataclass
class BildirimOzet:
    """Son bildirim işlem özeti."""

    bildirim_id: str = ""
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
            "notification_id": self.bildirim_id,
            "added": self.eklenen,
            "updated": self.guncellenen,
            "skipped": self.atlanan,
            "total": self.toplam,
            "engine": self.motor,
            "dry_run": self.dry_run,
            "device_id": self.cihaz_id,
            "detail": dict(self.detay),
        }


class BildirimKopru(BildirimSenkronu, ModulTabani):
    """
    Host bildirim köprüsü uygulaması.

    Motorlar:
      - dry_run: disk yazmaz, bellek içi
      - memory / sahte: bellek (zorla_sahte)
      - json: data/sync/notifications/notifications.json
    """

    ad = "sync.notifications"
    surum = "0.1.0"
    aciklama = "Capraz cihaz bildirim koprusu (JSON / dry_run)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        depo_yolu: Optional[Union[str, Path]] = None,
        max_govde: Optional[int] = None,
    ) -> None:
        ModulTabani.__init__(self)
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(
            self.ayarlar.al("mobile.features.notifications", True)
        )
        yol = depo_yolu
        if yol is None:
            yol = self.ayarlar.al("sync.notifications.store_path", None)
        self.depo_yolu = (
            Path(yol).expanduser() if yol else varsayilan_depo_yolu()
        )
        cfg_max = self.ayarlar.al("sync.notifications.max_body", None)
        if max_govde is not None:
            self.max_govde = int(max_govde)
        elif cfg_max is not None:
            self.max_govde = int(cfg_max)
        else:
            self.max_govde = _VARSAYILAN_MAX_GOVDE

        self._bildirimler: dict[str, dict[str, Any]] = {}
        self._giden: dict[str, list[str]] = {}  # cihaz → bildirim id kuyruğu
        self._motor = self._motor_sec()
        self._yuklendi = False

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise WhiteCoreError(
                "Bildirim koprusu config ile kapali (mobile.features.notifications=false)",
                kod="SYNC_0031",
                modul=self.ad,
            )
        self._motor = self._motor_sec()
        self._yukle()
        self._calisiyor = True
        audit_yaz(
            "notification.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "store": str(self.depo_yolu),
                "count": len(self._bildirimler),
                "max_body": self.max_govde,
            },
        )
        log.info(
            "Bildirim koprusu basladi (motor=%s, kayit=%s)",
            self._motor,
            len(self._bildirimler),
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()
        self._calisiyor = False
        audit_yaz(
            "notification.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "count": len(self._bildirimler)},
        )
        log.info("Bildirim koprusu durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ API

    @property
    def motor(self) -> str:
        return self._motor

    def listele(
        self,
        *,
        cihaz_id: Optional[str] = None,
        durum: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Bildirim kayıtlarını filtreleyerek döner."""
        self._ensure_yuklu()
        sonuc: list[dict[str, Any]] = []
        for b in self._bildirimler.values():
            if cihaz_id is not None and b.get("device_id") != cihaz_id:
                continue
            if durum is not None and b.get("status") != str(durum).lower():
                continue
            sonuc.append(dict(b))
        return sorted(
            sonuc, key=lambda x: (x.get("timestamp") or "", x["id"])
        )

    def bildirim_al(self, bildirim_id: str) -> Optional[dict[str, Any]]:
        self._ensure_yuklu()
        b = self._bildirimler.get(str(bildirim_id))
        return dict(b) if b else None

    async def ilet(
        self,
        cihaz_id: str,
        baslik: str,
        govde: str,
        *,
        veri: Optional[dict[str, Any]] = None,
        oncelik: str = "normal",
    ) -> None:
        """
        Bildirimi hedef cihaz kuyruğuna iletir.

        dry_run: bellekte tutar, disk yazmaz.
        json: depoya yazar + cihaz kuyruğuna koyar (üst katman WS ile iletir).
        """
        if not self._calisiyor:
            raise WhiteCoreError(
                "Bildirim koprusu calismiyor; once baslat() cagirin",
                kod="SYNC_0032",
                modul=self.ad,
            )
        cid = str(cihaz_id or "").strip()
        if not cid:
            raise WhiteCoreError(
                "cihaz_id gerekli",
                kod="SYNC_0033",
                modul=self.ad,
            )
        baslik_s = str(baslik or "").strip()
        govde_s = str(govde or "")
        if not baslik_s and not govde_s.strip():
            raise WhiteCoreError(
                "baslik veya govde gerekli",
                kod="SYNC_0034",
                modul=self.ad,
            )
        if len(govde_s) > self.max_govde:
            raise WhiteCoreError(
                f"Bildirim govde limiti asildi ({len(govde_s)} > {self.max_govde})",
                kod="SYNC_0035",
                modul=self.ad,
                detay={"size": len(govde_s), "max": self.max_govde},
            )
        if len(baslik_s) > 512:
            raise WhiteCoreError(
                "Bildirim basligi cok uzun",
                kod="SYNC_0035",
                modul=self.ad,
                detay={"title_len": len(baslik_s)},
            )

        nid = uuid4().hex
        kayit = bildirim_normalize(
            {
                "id": nid,
                "title": baslik_s or "WhiteCore",
                "body": govde_s,
                "status": BildirimDurumu.KUYRUKTA.value,
                "device_id": cid,
                "data": dict(veri) if isinstance(veri, dict) else {},
                "priority": oncelik,
                "source": "host",
            }
        )
        self._bildirimler[nid] = kayit
        self._giden.setdefault(cid, []).append(nid)
        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()

        audit_yaz(
            "notification.send",
            modul=self.ad,
            detay={
                "notification_id": nid,
                "device_id": cid,
                "title": kayit["title"],
                "engine": self._motor,
                "dry_run": self.dry_run,
            },
        )
        log.debug("Bildirim iletildi: %s -> %s", kayit["title"], cid)

    def kaydet(
        self,
        bildirimler: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> BildirimOzet:
        """Yerel depoya bildirim yazar (upsert)."""
        return self.uygula(bildirimler, cihaz_id=cihaz_id, kaynak="local")

    def uygula(
        self,
        bildirimler: list[dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
        kaynak: str = "remote",
    ) -> BildirimOzet:
        """Bildirim listesini depoya uygular (upsert). dry_run: disk yok."""
        self._ensure_yuklu()
        gelen = [bildirim_normalize(b) for b in bildirimler if isinstance(b, dict)]
        if cihaz_id:
            for b in gelen:
                b.setdefault("device_id", cihaz_id)

        eklenen = 0
        guncellenen = 0
        atlanan = 0
        son_id = ""

        for b in gelen:
            son_id = b["id"]
            eski = self._bildirimler.get(b["id"])
            if eski is None:
                self._bildirimler[b["id"]] = b
                eklenen += 1
            elif eski != b:
                self._bildirimler[b["id"]] = b
                guncellenen += 1
            else:
                atlanan += 1

        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()

        ozet = BildirimOzet(
            bildirim_id=son_id,
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=atlanan,
            toplam=len(self._bildirimler),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=cihaz_id,
            detay={"source": kaynak, "incoming": len(gelen)},
        )
        audit_yaz("notification.apply", modul=self.ad, detay=ozet.to_dict())
        return ozet

    def durum_guncelle(
        self,
        bildirim_id: str,
        durum: str,
    ) -> dict[str, Any]:
        """Bildirim durumunu günceller (delivered / read / failed / cancelled)."""
        self._ensure_yuklu()
        nid = str(bildirim_id or "").strip()
        kayit = self._bildirimler.get(nid)
        if kayit is None:
            raise WhiteCoreError(
                f"Bildirim bulunamadi: {nid}",
                kod="SYNC_0036",
                modul=self.ad,
            )
        try:
            yeni = BildirimDurumu(str(durum).lower()).value
        except ValueError as hata:
            raise WhiteCoreError(
                f"Gecersiz bildirim durumu: {durum}",
                kod="SYNC_0037",
                modul=self.ad,
                detay={"status": durum},
            ) from hata
        kayit["status"] = yeni
        kayit["meta"] = dict(kayit.get("meta") or {})
        kayit["meta"]["status_updated"] = _utc_iso()
        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()
        audit_yaz(
            "notification.status",
            modul=self.ad,
            detay={"notification_id": nid, "status": yeni},
        )
        return dict(kayit)

    def iptal(self, bildirim_id: str) -> dict[str, Any]:
        """Bildirimi iptal eder; giden kuyruktan çıkarır."""
        kayit = self.durum_guncelle(bildirim_id, BildirimDurumu.IPTAL.value)
        nid = kayit["id"]
        cid = kayit.get("device_id")
        if cid and cid in self._giden:
            self._giden[cid] = [x for x in self._giden[cid] if x != nid]
            if not self._giden[cid]:
                self._giden.pop(cid, None)
        return kayit

    def giden_cek(self, cihaz_id: str) -> list[dict[str, Any]]:
        """Cihaz giden bildirim kuyruğunu alıp temizler."""
        ids = self._giden.pop(str(cihaz_id), [])
        sonuc: list[dict[str, Any]] = []
        for nid in ids:
            b = self._bildirimler.get(nid)
            if b:
                # kuyruktan çıktı → delivered (üst katman iletti varsay)
                if b.get("status") == BildirimDurumu.KUYRUKTA.value:
                    b["status"] = BildirimDurumu.ILETILDI.value
                sonuc.append(dict(b))
        if sonuc and self._motor == "json" and not self.dry_run:
            self._kaydet_disk()
        return sonuc

    # ------------------------------------------------------------------ protokol

    def notification_mesaji(
        self,
        *,
        bildirim_id: Optional[str] = None,
        cihaz_id: Optional[str] = None,
        islem: str = "push",
    ) -> WsMesaj:
        """
        protokol.MesajTipi.NOTIFICATION zarfı üretir.

        payload: {op, notification?, notifications?, title?, body?}
        """
        self._ensure_yuklu()
        yuk: dict[str, Any] = {"op": islem}
        if bildirim_id:
            b = self._bildirimler.get(str(bildirim_id))
            if b is None:
                raise WhiteCoreError(
                    f"Bildirim bulunamadi: {bildirim_id}",
                    kod="SYNC_0036",
                    modul=self.ad,
                )
            yuk["notification"] = dict(b)
            yuk["title"] = b.get("title")
            yuk["body"] = b.get("body")
        else:
            yuk["notifications"] = self.listele(cihaz_id=cihaz_id)
        return mesaj_olustur(MesajTipi.NOTIFICATION, yuk, cihaz_id=cihaz_id)

    def notification_isle(
        self,
        mesaj: Union[WsMesaj, dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Gelen NOTIFICATION mesajını uygular; sunucu ack detayı ile uyumlu özet.

        op:
          - push / deliver / put / apply: bildirimi uygula / kuyruğa al
          - list / pull: bildirim listesi
          - get: tek bildirim
          - ack / delivered: durumu delivered yap
          - read: durumu read yap
          - cancel: iptal
        """
        if isinstance(mesaj, WsMesaj):
            if mesaj.tip is not MesajTipi.NOTIFICATION:
                raise WhiteCoreError(
                    f"Beklenen tip notification, gelen: {mesaj.tip.value}",
                    kod="SYNC_0038",
                    modul=self.ad,
                )
            yuk = dict(mesaj.yuk)
            cid = cihaz_id or mesaj.cihaz_id
        else:
            yuk = dict(mesaj)
            cid = cihaz_id or yuk.get("device_id") or yuk.get("cihaz_id")

        op = str(yuk.get("op") or yuk.get("islem") or "push").lower()

        if op in {"list", "pull", "liste"}:
            liste = self.listele(cihaz_id=str(cid) if cid else None)
            return {
                "ok": True,
                "type": MesajTipi.NOTIFICATION.value,
                "op": "list",
                "device_id": cid,
                "notifications": liste,
                "count": len(liste),
            }

        if op == "get":
            nid = str(yuk.get("notification_id") or yuk.get("id") or "")
            b = self.bildirim_al(nid)
            if b is None:
                raise WhiteCoreError(
                    f"Bildirim bulunamadi: {nid}",
                    kod="SYNC_0036",
                    modul=self.ad,
                )
            return {
                "ok": True,
                "type": MesajTipi.NOTIFICATION.value,
                "op": "get",
                "notification": b,
            }

        if op in {"ack", "delivered"}:
            nid = str(yuk.get("notification_id") or yuk.get("id") or "")
            b = self.durum_guncelle(nid, BildirimDurumu.ILETILDI.value)
            return {
                "ok": True,
                "type": MesajTipi.NOTIFICATION.value,
                "op": "delivered",
                "notification": b,
            }

        if op == "read":
            nid = str(yuk.get("notification_id") or yuk.get("id") or "")
            b = self.durum_guncelle(nid, BildirimDurumu.OKUNDU.value)
            return {
                "ok": True,
                "type": MesajTipi.NOTIFICATION.value,
                "op": "read",
                "notification": b,
            }

        if op == "cancel":
            b = self.iptal(str(yuk.get("notification_id") or yuk.get("id") or ""))
            return {
                "ok": True,
                "type": MesajTipi.NOTIFICATION.value,
                "op": "cancel",
                "notification": b,
            }

        # push / deliver / put / apply
        ozet = self._uzak_uygula(yuk, cihaz_id=str(cid) if cid else None)
        return {
            "ok": True,
            "type": MesajTipi.NOTIFICATION.value,
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
            "count": len(self._bildirimler),
            "max_body": self.max_govde,
            "devices_queued": {k: len(v) for k, v in self._giden.items()},
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
                self._bildirimler = {}
            self._yuklendi = True
            return
        paket = _depo_yukle(self.depo_yolu)
        self._bildirimler = {
            b["id"]: b for b in (paket.get("notifications") or [])
        }
        self._yuklendi = True

    def _kaydet_disk(self) -> None:
        _depo_kaydet(
            self.depo_yolu,
            {
                "version": _DEPO_SURUM,
                "notifications": list(self._bildirimler.values()),
            },
        )

    def _uzak_uygula(
        self,
        yuk: dict[str, Any],
        *,
        cihaz_id: Optional[str] = None,
    ) -> BildirimOzet:
        """Uzak push yükünü depoya / kuyruğa uygular."""
        self._ensure_yuklu()
        ham_liste = yuk.get("notifications") or yuk.get("bildirimler")
        if isinstance(ham_liste, list) and ham_liste:
            return self.uygula(
                ham_liste,
                cihaz_id=cihaz_id,
                kaynak="notification",
            )

        ham_b = yuk.get("notification") or yuk.get("bildirim") or {}
        if not isinstance(ham_b, dict):
            ham_b = {}
        if not ham_b and (
            yuk.get("title") is not None
            or yuk.get("baslik") is not None
            or yuk.get("body") is not None
            or yuk.get("govde") is not None
        ):
            ham_b = {
                "id": yuk.get("notification_id") or yuk.get("id"),
                "title": yuk.get("title") if "title" in yuk else yuk.get("baslik"),
                "body": yuk.get("body") if "body" in yuk else yuk.get("govde"),
                "data": yuk.get("data") or yuk.get("veri"),
                "priority": yuk.get("priority") or yuk.get("oncelik"),
                "device_id": cihaz_id,
                "status": BildirimDurumu.KUYRUKTA.value,
            }
        if not ham_b:
            raise WhiteCoreError(
                "NOTIFICATION yukunde bildirim bilgisi yok",
                kod="SYNC_0039",
                modul=self.ad,
            )
        if cihaz_id:
            ham_b.setdefault("device_id", cihaz_id)
        ham_b.setdefault("status", BildirimDurumu.KUYRUKTA.value)
        ham_b.setdefault("source", "remote")

        kayit = bildirim_normalize(ham_b)
        if len(kayit["body"]) > self.max_govde:
            raise WhiteCoreError(
                f"Bildirim govde limiti asildi ({len(kayit['body'])} > {self.max_govde})",
                kod="SYNC_0035",
                modul=self.ad,
            )

        onceki = self._bildirimler.get(kayit["id"])
        eklenen = 0 if onceki else 1
        guncellenen = 1 if onceki else 0
        self._bildirimler[kayit["id"]] = kayit

        # Hedef cihaza kuyrukla (push)
        cid = kayit.get("device_id") or cihaz_id
        if cid:
            kuyruk = self._giden.setdefault(str(cid), [])
            if kayit["id"] not in kuyruk:
                kuyruk.append(kayit["id"])

        if self._motor == "json" and not self.dry_run:
            self._kaydet_disk()

        ozet = BildirimOzet(
            bildirim_id=kayit["id"],
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=0,
            toplam=len(self._bildirimler),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=str(cid) if cid else None,
            detay={"title": kayit["title"]},
        )
        audit_yaz("notification.remote_apply", modul=self.ad, detay=ozet.to_dict())
        return ozet


__all__ = [
    "BildirimKopru",
    "BildirimDurumu",
    "BildirimOzet",
    "varsayilan_depo_yolu",
    "bildirim_normalize",
]
