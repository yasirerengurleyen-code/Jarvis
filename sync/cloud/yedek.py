"""
sync/cloud/yedek.py
-------------------
Yerel / bulut yedek senkronu (host tarafı).

Görev:
- Yerel JSON + snapshot deposunda yedek kayıtlarını tutmak
- Buluta yükle / buluttan indir (gerçek bulut yoksa sahte bellek köprüsü)
- dry_run / sahte modda ağ ve disk olmadan test edilebilir olmak
- protokol EVENT (kind=cloud_backup) yükü üretmek / işlemek
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

log = logger_al("sync.cloud.yedek")

_KOK = Path(__file__).resolve().parents[2]
_VARSAYILAN_DEPO = _KOK / "data" / "sync" / "cloud"
_DEPO_SURUM = 1
_VARSAYILAN_MAX_BAYT = 5 * 1024 * 1024  # 5 MiB payload


class YedekDurumu(str, Enum):
    """Yedek yaşam döngüsü."""

    YEREL = "local"
    YUKLENIYOR = "uploading"
    BULUTTA = "cloud"
    INDIRILIYOR = "downloading"
    GERI_YUKLENDI = "restored"
    BASARISIZ = "failed"
    SILINDI = "deleted"


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def varsayilan_depo_yolu() -> Path:
    return _VARSAYILAN_DEPO


def yedek_normalize(ham: dict[str, Any]) -> dict[str, Any]:
    """
    Gelen sözlüğü kanonik yedek kaydına çevirir.

    Kabul (TR / EN):
      id/yedek_id/backup_id, label/etiket, status/durum,
      created/olusturuldu, updated/guncellendi, size/boyut,
      device_id/cihaz_id, kind/tur, sha256/hash, meta, cloud_id
    """
    if not isinstance(ham, dict):
        raise WhiteCoreError(
            "Yedek kaydi sozluk olmali",
            kod="SYNC_0040",
            modul="sync.cloud",
        )
    yid = ham.get("id") or ham.get("yedek_id") or ham.get("backup_id") or uuid4().hex
    etiket = ham.get("label") if "label" in ham else ham.get("etiket")
    if etiket is None:
        etiket = "backup"
    durum_ham = ham.get("status") or ham.get("durum") or YedekDurumu.YEREL.value
    try:
        durum = YedekDurumu(str(durum_ham).lower()).value
    except ValueError:
        durum = YedekDurumu.YEREL.value
    boyut = ham.get("size") if "size" in ham else ham.get("boyut")
    try:
        boyut_i = int(boyut) if boyut is not None else 0
    except (TypeError, ValueError):
        boyut_i = 0
    if boyut_i < 0:
        boyut_i = 0
    kayit: dict[str, Any] = {
        "id": str(yid),
        "label": str(etiket),
        "status": durum,
        "size": boyut_i,
        "kind": str(ham.get("kind") or ham.get("tur") or "snapshot"),
        "sha256": str(ham.get("sha256") or ham.get("hash") or ""),
        "created": str(ham.get("created") or ham.get("olusturuldu") or _utc_iso()),
        "updated": str(ham.get("updated") or ham.get("guncellendi") or _utc_iso()),
        "meta": dict(ham["meta"]) if isinstance(ham.get("meta"), dict) else {},
    }
    cihaz = ham.get("device_id") or ham.get("cihaz_id")
    if cihaz is not None:
        kayit["device_id"] = str(cihaz)
    cloud_id = ham.get("cloud_id") or ham.get("bulut_id")
    if cloud_id is not None:
        kayit["cloud_id"] = str(cloud_id)
    return kayit


@dataclass
class YedekOzet:
    """Son yedek işlem özeti."""

    yedek_id: str = ""
    eklenen: int = 0
    guncellenen: int = 0
    atlanan: int = 0
    toplam: int = 0
    motor: str = "local"
    dry_run: bool = False
    cihaz_id: Optional[str] = None
    detay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.yedek_id,
            "added": self.eklenen,
            "updated": self.guncellenen,
            "skipped": self.atlanan,
            "total": self.toplam,
            "engine": self.motor,
            "dry_run": self.dry_run,
            "device_id": self.cihaz_id,
            "detail": dict(self.detay),
        }


def _manifest_yukle(yol: Path) -> dict[str, Any]:
    bos = {
        "version": _DEPO_SURUM,
        "updated": _utc_iso(),
        "backups": [],
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
            "backups": [yedek_normalize(x) for x in ham if isinstance(x, dict)],
        }
    if not isinstance(ham, dict):
        return bos
    liste = ham.get("backups") or ham.get("yedekler") or []
    if not isinstance(liste, list):
        liste = []
    return {
        "version": int(ham.get("version") or _DEPO_SURUM),
        "updated": str(ham.get("updated") or _utc_iso()),
        "backups": [yedek_normalize(x) for x in liste if isinstance(x, dict)],
    }


def _manifest_kaydet(yol: Path, paket: dict[str, Any]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    cikti = {
        "version": int(paket.get("version") or _DEPO_SURUM),
        "updated": _utc_iso(),
        "backups": list(paket.get("backups") or []),
    }
    yol.write_text(
        json.dumps(cikti, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class BulutYedek(ModulTabani):
    """
    Host yerel / bulut yedek senkron uygulaması.

    Motorlar:
      - dry_run: disk / ağ yazmaz, bellek içi
      - sahte: bellek + sahte bulut (zorla_sahte veya bulut yok)
      - local: data/sync/cloud + sahte bulut köprüsü
    """

    ad = "sync.cloud"
    surum = "0.1.0"
    aciklama = "Yerel / bulut yedek senkronu (local / sahte / dry_run)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        depo_yolu: Optional[Union[str, Path]] = None,
        max_bayt: Optional[int] = None,
        bulut_endpoint: Optional[str] = None,
    ) -> None:
        ModulTabani.__init__(self)
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(
            self.ayarlar.al("mobile.features.cloud_backup", True)
        )
        yol = depo_yolu
        if yol is None:
            yol = self.ayarlar.al("sync.cloud.store_path", None)
        self.depo_yolu = (
            Path(yol).expanduser() if yol else varsayilan_depo_yolu()
        )
        cfg_max = self.ayarlar.al("sync.cloud.max_bytes", None)
        if max_bayt is not None:
            self.max_bayt = int(max_bayt)
        elif cfg_max is not None:
            self.max_bayt = int(cfg_max)
        else:
            self.max_bayt = _VARSAYILAN_MAX_BAYT

        ep = bulut_endpoint
        if ep is None:
            ep = self.ayarlar.al("sync.cloud.endpoint", None)
        self.bulut_endpoint = str(ep).strip() if ep else ""
        # Gerçek bulut istemcisi bu aşamada yok → her zaman sahte bulut
        self._bulut_musait = False

        self._yedekler: dict[str, dict[str, Any]] = {}
        self._icerik: dict[str, dict[str, Any]] = {}  # yerel payload (bellek)
        self._bulut: dict[str, dict[str, Any]] = {}  # sahte bulut: id → paket
        self._motor = self._motor_sec()
        self._yuklendi = False

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise WhiteCoreError(
                "Bulut yedek config ile kapali (mobile.features.cloud_backup=false)",
                kod="SYNC_0041",
                modul=self.ad,
            )
        self._motor = self._motor_sec()
        self._yukle()
        if self._motor == "local" and not self.dry_run:
            self.snapshot_dizini.mkdir(parents=True, exist_ok=True)
        self._calisiyor = True
        audit_yaz(
            "cloud_backup.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "store": str(self.depo_yolu),
                "count": len(self._yedekler),
                "cloud_available": self._bulut_musait,
                "max_bytes": self.max_bayt,
            },
        )
        log.info(
            "Bulut yedek basladi (motor=%s, kayit=%s, bulut=%s)",
            self._motor,
            len(self._yedekler),
            "gercek" if self._bulut_musait else "sahte",
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()
        self._calisiyor = False
        audit_yaz(
            "cloud_backup.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "count": len(self._yedekler)},
        )
        log.info("Bulut yedek durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ yollar

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def manifest_yolu(self) -> Path:
        return self.depo_yolu / "backups.json"

    @property
    def snapshot_dizini(self) -> Path:
        return self.depo_yolu / "snapshots"

    @property
    def bulut_sahte_mi(self) -> bool:
        """Gerçek bulut yoksa True (bu aşamada her zaman)."""
        return not self._bulut_musait

    # ------------------------------------------------------------------ API

    def listele(
        self,
        *,
        cihaz_id: Optional[str] = None,
        durum: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Yedek kayıtlarını filtreleyerek döner."""
        self._ensure_yuklu()
        sonuc: list[dict[str, Any]] = []
        for y in self._yedekler.values():
            if cihaz_id is not None and y.get("device_id") != cihaz_id:
                continue
            if durum is not None and y.get("status") != str(durum).lower():
                continue
            sonuc.append(dict(y))
        return sorted(sonuc, key=lambda x: (x.get("created") or "", x["id"]))

    def yedek_al(self, yedek_id: str) -> Optional[dict[str, Any]]:
        self._ensure_yuklu()
        y = self._yedekler.get(str(yedek_id))
        return dict(y) if y else None

    def icerik_al(self, yedek_id: str) -> dict[str, Any]:
        """Yedek payload'ını döner."""
        self._ensure_yuklu()
        yid = str(yedek_id)
        if yid not in self._yedekler:
            raise WhiteCoreError(
                f"Yedek bulunamadi: {yid}",
                kod="SYNC_0042",
                modul=self.ad,
            )
        return dict(self._icerik_oku(yid))

    async def yedekle(
        self,
        veri: dict[str, Any],
        *,
        etiket: str = "backup",
        cihaz_id: Optional[str] = None,
        tur: str = "snapshot",
        buluta_yukle: bool = False,
    ) -> str:
        """
        Yerel yedek oluşturur; isteğe bağlı buluta yükler.

        dry_run / sahte: bellek; local: snapshot JSON + manifest.
        Dönüş: yedek_id
        """
        self._calisiyor_mi()
        if not isinstance(veri, dict):
            raise WhiteCoreError(
                "Yedek verisi sozluk olmali",
                kod="SYNC_0044",
                modul=self.ad,
            )
        ham = json.dumps(veri, ensure_ascii=False, separators=(",", ":"))
        boyut = len(ham.encode("utf-8"))
        if boyut > self.max_bayt:
            raise WhiteCoreError(
                f"Yedek boyutu limiti asildi ({boyut} > {self.max_bayt})",
                kod="SYNC_0045",
                modul=self.ad,
                detay={"size": boyut, "max": self.max_bayt},
            )

        yid = uuid4().hex
        payload = dict(veri)
        kayit = yedek_normalize(
            {
                "id": yid,
                "label": etiket,
                "status": YedekDurumu.YEREL.value,
                "size": boyut,
                "kind": tur,
                "device_id": cihaz_id,
                "sha256": "",  # isteğe bağlı; boş bırakılabilir
            }
        )

        if self._motor == "local" and not self.dry_run:
            self._snapshot_yaz(yid, payload)
        else:
            self._icerik[yid] = payload

        self._yedekler[yid] = kayit
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()

        audit_yaz(
            "cloud_backup.create",
            modul=self.ad,
            detay={
                "backup_id": yid,
                "label": etiket,
                "size": boyut,
                "engine": self._motor,
                "dry_run": self.dry_run,
                "device_id": cihaz_id,
            },
        )
        log.debug("Yedek olusturuldu: %s (%s bayt)", yid, boyut)

        if buluta_yukle:
            await self.yukle(yid)

        return yid

    async def yukle(self, yedek_id: str) -> YedekOzet:
        """
        Yerel yedeği buluta yükler.

        Gerçek endpoint yoksa sahte bulut bellek deposuna yazar (offline).
        """
        self._calisiyor_mi()
        return self._yukle_govde(yedek_id)

    async def indir(self, cloud_id: str) -> str:
        """
        Buluttan (veya sahte depodan) yedeği yerel depoya indirir.

        Dönüş: yerel yedek_id
        """
        self._calisiyor_mi()
        return self._indir_govde(cloud_id)

    async def geri_yukle(self, yedek_id: str) -> dict[str, Any]:
        """Yerel yedekten payload döner; durumu restored yapar."""
        self._calisiyor_mi()
        return self._geri_yukle_govde(yedek_id)

    def sil(self, yedek_id: str, *, buluttan_da: bool = True) -> dict[str, Any]:
        """Yedeği silindi olarak işaretler; isteğe bağlı sahte buluttan kaldırır."""
        self._ensure_yuklu()
        yid = str(yedek_id)
        kayit = self._yedekler.get(yid)
        if kayit is None:
            raise WhiteCoreError(
                f"Yedek bulunamadi: {yid}",
                kod="SYNC_0042",
                modul=self.ad,
            )
        cid = kayit.get("cloud_id")
        if buluttan_da and cid:
            self._bulut.pop(str(cid), None)
        self._icerik.pop(yid, None)
        if self._motor == "local" and not self.dry_run:
            snap = self._snapshot_yolu(yid)
            if snap.is_file():
                try:
                    snap.unlink()
                except OSError:
                    pass
        kayit["status"] = YedekDurumu.SILINDI.value
        kayit["updated"] = _utc_iso()
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()
        audit_yaz(
            "cloud_backup.delete",
            modul=self.ad,
            detay={"backup_id": yid, "cloud_id": cid},
        )
        return dict(kayit)

    def bulut_listele(self) -> list[dict[str, Any]]:
        """Sahte / bellek bulutundaki paket özetlerini döner."""
        sonuc: list[dict[str, Any]] = []
        for cid, paket in self._bulut.items():
            b = paket.get("backup") if isinstance(paket.get("backup"), dict) else {}
            sonuc.append(
                {
                    "cloud_id": cid,
                    "backup_id": b.get("id"),
                    "label": b.get("label"),
                    "size": b.get("size"),
                    "uploaded": paket.get("uploaded"),
                    "fake": bool(paket.get("fake", True)),
                }
            )
        return sorted(sonuc, key=lambda x: (x.get("uploaded") or "", x["cloud_id"]))

    # ------------------------------------------------------------------ protokol

    def cloud_backup_mesaji(
        self,
        *,
        yedek_id: Optional[str] = None,
        cihaz_id: Optional[str] = None,
        islem: str = "list",
        icerik_dahil: bool = False,
    ) -> WsMesaj:
        """
        protokol.MesajTipi.EVENT zarfı (kind=cloud_backup) üretir.

        payload: {kind, op, backup?, backups?, payload?}
        """
        self._ensure_yuklu()
        yuk: dict[str, Any] = {"kind": "cloud_backup", "op": islem}
        if yedek_id:
            y = self._yedekler.get(str(yedek_id))
            if y is None:
                raise WhiteCoreError(
                    f"Yedek bulunamadi: {yedek_id}",
                    kod="SYNC_0042",
                    modul=self.ad,
                )
            yuk["backup"] = dict(y)
            if icerik_dahil:
                yuk["payload"] = self._icerik_oku(str(yedek_id))
        else:
            yuk["backups"] = self.listele(cihaz_id=cihaz_id)
        return mesaj_olustur(MesajTipi.EVENT, yuk, cihaz_id=cihaz_id)

    def cloud_backup_isle(
        self,
        mesaj: Union[WsMesaj, dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Gelen EVENT/cloud_backup mesajını uygular.

        op:
          - list / pull: yedek listesi
          - get: tek yedek (+ isteğe bağlı payload)
          - create / put / apply: uzak yedek uygula
          - upload: buluta yükle
          - download: buluttan indir
          - restore: geri yükle
          - delete / cancel: sil
        """
        if isinstance(mesaj, WsMesaj):
            if mesaj.tip is not MesajTipi.EVENT:
                raise WhiteCoreError(
                    f"Beklenen tip event, gelen: {mesaj.tip.value}",
                    kod="SYNC_0048",
                    modul=self.ad,
                )
            yuk = dict(mesaj.yuk)
            cid = cihaz_id or mesaj.cihaz_id
        else:
            yuk = dict(mesaj)
            cid = cihaz_id or yuk.get("device_id") or yuk.get("cihaz_id")

        kind = str(yuk.get("kind") or yuk.get("tur") or "cloud_backup").lower()
        if kind not in {"cloud_backup", "backup", "yedek"}:
            raise WhiteCoreError(
                f"Beklenen kind cloud_backup, gelen: {kind}",
                kod="SYNC_0048",
                modul=self.ad,
            )

        op = str(yuk.get("op") or yuk.get("islem") or "list").lower()

        if op in {"list", "pull", "liste"}:
            liste = self.listele(cihaz_id=str(cid) if cid else None)
            return {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "list",
                "device_id": cid,
                "backups": liste,
                "count": len(liste),
            }

        if op == "get":
            yid = str(yuk.get("backup_id") or yuk.get("yedek_id") or yuk.get("id") or "")
            y = self.yedek_al(yid)
            if y is None:
                raise WhiteCoreError(
                    f"Yedek bulunamadi: {yid}",
                    kod="SYNC_0042",
                    modul=self.ad,
                )
            out: dict[str, Any] = {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "get",
                "backup": y,
            }
            if bool(yuk.get("include_payload") or yuk.get("icerik_dahil")):
                out["payload"] = self.icerik_al(yid)
            return out

        if op == "upload":
            self._calisiyor_mi()
            yid = str(yuk.get("backup_id") or yuk.get("yedek_id") or yuk.get("id") or "")
            ozet = self._yukle_govde(yid)
            return {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "upload",
                **ozet.to_dict(),
            }

        if op == "download":
            self._calisiyor_mi()
            cid_b = str(
                yuk.get("cloud_id")
                or yuk.get("bulut_id")
                or yuk.get("backup_id")
                or yuk.get("id")
                or ""
            )
            yid = self._indir_govde(cid_b)
            return {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "download",
                "backup_id": yid,
                "backup": self.yedek_al(yid),
            }

        if op == "restore":
            self._calisiyor_mi()
            yid = str(yuk.get("backup_id") or yuk.get("yedek_id") or yuk.get("id") or "")
            payload = self._geri_yukle_govde(yid)
            return {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "restore",
                "backup_id": yid,
                "payload": payload,
            }

        if op in {"delete", "cancel", "sil"}:
            y = self.sil(
                str(yuk.get("backup_id") or yuk.get("yedek_id") or yuk.get("id") or "")
            )
            return {
                "ok": True,
                "type": MesajTipi.EVENT.value,
                "kind": "cloud_backup",
                "op": "delete",
                "backup": y,
            }

        # create / put / apply
        ozet = self._uzak_uygula(yuk, cihaz_id=str(cid) if cid else None)
        return {
            "ok": True,
            "type": MesajTipi.EVENT.value,
            "kind": "cloud_backup",
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
            "count": len(
                [
                    y
                    for y in self._yedekler.values()
                    if y.get("status") != YedekDurumu.SILINDI.value
                ]
            ),
            "cloud_count": len(self._bulut),
            "cloud_fake": self.bulut_sahte_mi,
            "endpoint": self.bulut_endpoint or "sahte://memory",
            "max_bytes": self.max_bayt,
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "local"

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise WhiteCoreError(
                "Bulut yedek calismiyor; once baslat() cagirin",
                kod="SYNC_0043",
                modul=self.ad,
            )

    def _ensure_yuklu(self) -> None:
        if not self._yuklendi:
            self._yukle()

    def _yukle(self) -> None:
        if self._motor in {"dry_run", "sahte"}:
            if not self._yuklendi:
                self._yedekler = {}
                self._icerik = {}
                self._bulut = {}
            self._yuklendi = True
            return
        paket = _manifest_yukle(self.manifest_yolu)
        self._yedekler = {y["id"]: y for y in (paket.get("backups") or [])}
        self._icerik = {}
        self._yuklendi = True

    def _kaydet_manifest(self) -> None:
        _manifest_kaydet(
            self.manifest_yolu,
            {
                "version": _DEPO_SURUM,
                "backups": list(self._yedekler.values()),
            },
        )

    def _snapshot_yolu(self, yedek_id: str) -> Path:
        return self.snapshot_dizini / f"{yedek_id}.json"

    def _snapshot_yaz(self, yedek_id: str, payload: dict[str, Any]) -> None:
        self.snapshot_dizini.mkdir(parents=True, exist_ok=True)
        yol = self._snapshot_yolu(yedek_id)
        yol.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _icerik_oku(self, yid: str) -> dict[str, Any]:
        if yid in self._icerik:
            return dict(self._icerik[yid])
        if self._motor == "local":
            yol = self._snapshot_yolu(yid)
            if yol.is_file():
                try:
                    ham = json.loads(yol.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as hata:
                    raise WhiteCoreError(
                        f"Yedek icerigi okunamadi: {yid}",
                        kod="SYNC_0049",
                        modul=self.ad,
                    ) from hata
                if not isinstance(ham, dict):
                    raise WhiteCoreError(
                        f"Yedek icerigi sozluk olmali: {yid}",
                        kod="SYNC_0049",
                        modul=self.ad,
                    )
                self._icerik[yid] = ham
                return dict(ham)
        raise WhiteCoreError(
            f"Yedek icerigi yok: {yid}",
            kod="SYNC_0049",
            modul=self.ad,
        )

    def _yukle_govde(self, yedek_id: str) -> YedekOzet:
        """Yerel → sahte/gerçek bulut yükleme gövdesi."""
        self._ensure_yuklu()
        yid = str(yedek_id or "").strip()
        kayit = self._yedekler.get(yid)
        if kayit is None:
            raise WhiteCoreError(
                f"Yedek bulunamadi: {yid}",
                kod="SYNC_0042",
                modul=self.ad,
            )
        if kayit.get("status") == YedekDurumu.SILINDI.value:
            raise WhiteCoreError(
                "Silinmis yedek yuklenemez",
                kod="SYNC_0046",
                modul=self.ad,
                detay={"backup_id": yid},
            )
        kayit["status"] = YedekDurumu.YUKLENIYOR.value
        kayit["updated"] = _utc_iso()
        payload = self._icerik_oku(yid)
        cloud_id = kayit.get("cloud_id") or f"cloud-{yid}"
        paket = {
            "cloud_id": cloud_id,
            "backup": dict(kayit),
            "payload": dict(payload),
            "uploaded": _utc_iso(),
            "fake": self.bulut_sahte_mi,
            "endpoint": self.bulut_endpoint or "sahte://memory",
        }
        self._bulut[cloud_id] = paket
        kayit["status"] = YedekDurumu.BULUTTA.value
        kayit["cloud_id"] = cloud_id
        kayit["updated"] = _utc_iso()
        kayit["meta"] = dict(kayit.get("meta") or {})
        kayit["meta"]["cloud_fake"] = self.bulut_sahte_mi
        kayit["meta"]["uploaded"] = paket["uploaded"]
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()
        ozet = YedekOzet(
            yedek_id=yid,
            guncellenen=1,
            toplam=len(self._yedekler),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=kayit.get("device_id"),
            detay={
                "cloud_id": cloud_id,
                "cloud_fake": self.bulut_sahte_mi,
                "op": "upload",
            },
        )
        audit_yaz("cloud_backup.upload", modul=self.ad, detay=ozet.to_dict())
        return ozet

    def _indir_govde(self, cloud_id: str) -> str:
        """Bulut → yerel indirme gövdesi."""
        self._ensure_yuklu()
        cid = str(cloud_id or "").strip()
        paket = self._bulut.get(cid)
        if paket is None:
            for yid, y in self._yedekler.items():
                if y.get("cloud_id") == cid or yid == cid:
                    if yid in self._icerik or (
                        self._motor == "local" and self._snapshot_yolu(yid).is_file()
                    ):
                        return yid
            raise WhiteCoreError(
                f"Bulut yedegi bulunamadi: {cid}",
                kod="SYNC_0047",
                modul=self.ad,
            )
        ham_y = paket.get("backup") if isinstance(paket.get("backup"), dict) else {}
        payload = paket.get("payload") if isinstance(paket.get("payload"), dict) else {}
        yid = str(ham_y.get("id") or uuid4().hex)
        kayit = yedek_normalize(
            {
                **ham_y,
                "id": yid,
                "status": YedekDurumu.YEREL.value,
                "cloud_id": cid,
            }
        )
        kayit["updated"] = _utc_iso()
        kayit["meta"] = dict(kayit.get("meta") or {})
        kayit["meta"]["downloaded"] = _utc_iso()
        kayit["meta"]["cloud_fake"] = bool(paket.get("fake", True))
        boyut = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        if boyut > self.max_bayt:
            raise WhiteCoreError(
                f"Yedek boyutu limiti asildi ({boyut} > {self.max_bayt})",
                kod="SYNC_0045",
                modul=self.ad,
            )
        kayit["size"] = boyut
        if self._motor == "local" and not self.dry_run:
            self._snapshot_yaz(yid, dict(payload))
        else:
            self._icerik[yid] = dict(payload)
        self._yedekler[yid] = kayit
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()
        audit_yaz(
            "cloud_backup.download",
            modul=self.ad,
            detay={
                "backup_id": yid,
                "cloud_id": cid,
                "engine": self._motor,
                "dry_run": self.dry_run,
            },
        )
        return yid

    def _geri_yukle_govde(self, yedek_id: str) -> dict[str, Any]:
        """Yerel yedekten payload geri yükleme gövdesi."""
        self._ensure_yuklu()
        yid = str(yedek_id or "").strip()
        kayit = self._yedekler.get(yid)
        if kayit is None:
            raise WhiteCoreError(
                f"Yedek bulunamadi: {yid}",
                kod="SYNC_0042",
                modul=self.ad,
            )
        if kayit.get("status") == YedekDurumu.SILINDI.value:
            raise WhiteCoreError(
                "Silinmis yedek geri yuklenemez",
                kod="SYNC_0046",
                modul=self.ad,
            )
        payload = self._icerik_oku(yid)
        kayit["status"] = YedekDurumu.GERI_YUKLENDI.value
        kayit["updated"] = _utc_iso()
        kayit["meta"] = dict(kayit.get("meta") or {})
        kayit["meta"]["restored"] = _utc_iso()
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()
        audit_yaz(
            "cloud_backup.restore",
            modul=self.ad,
            detay={"backup_id": yid, "engine": self._motor},
        )
        return dict(payload)

    def _uzak_uygula(
        self,
        yuk: dict[str, Any],
        *,
        cihaz_id: Optional[str] = None,
    ) -> YedekOzet:
        """Uzak create/put yükünü yerel depoya uygular."""
        self._ensure_yuklu()
        ham_y = yuk.get("backup") or yuk.get("yedek") or {}
        if not isinstance(ham_y, dict):
            ham_y = {}
        payload = yuk.get("payload") or yuk.get("veri") or yuk.get("data")
        if not isinstance(payload, dict):
            payload = {}
        if not ham_y and not payload:
            raise WhiteCoreError(
                "cloud_backup yukunde yedek bilgisi yok",
                kod="SYNC_0050",
                modul=self.ad,
            )
        if cihaz_id:
            ham_y.setdefault("device_id", cihaz_id)

        if payload:
            boyut = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            if boyut > self.max_bayt:
                raise WhiteCoreError(
                    f"Yedek boyutu limiti asildi ({boyut} > {self.max_bayt})",
                    kod="SYNC_0045",
                    modul=self.ad,
                )
            ham_y["size"] = boyut

        kayit = yedek_normalize(ham_y)
        yid = kayit["id"]
        onceki = self._yedekler.get(yid)
        eklenen = 0 if onceki else 1
        guncellenen = 1 if onceki else 0

        if payload:
            if self._motor == "local" and not self.dry_run:
                self._snapshot_yaz(yid, dict(payload))
            else:
                self._icerik[yid] = dict(payload)
            kayit["status"] = kayit.get("status") or YedekDurumu.YEREL.value

        self._yedekler[yid] = kayit
        if self._motor == "local" and not self.dry_run:
            self._kaydet_manifest()

        ozet = YedekOzet(
            yedek_id=yid,
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=0,
            toplam=len(self._yedekler),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=cihaz_id,
            detay={"label": kayit["label"], "has_payload": bool(payload)},
        )
        audit_yaz("cloud_backup.apply", modul=self.ad, detay=ozet.to_dict())
        return ozet


__all__ = [
    "BulutYedek",
    "YedekDurumu",
    "YedekOzet",
    "varsayilan_depo_yolu",
    "yedek_normalize",
]
