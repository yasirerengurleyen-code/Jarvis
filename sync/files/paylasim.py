"""
sync/files/paylasim.py
----------------------
Cihazlar arası dosya paylaşımı (host tarafı).

Görev:
- Yerel staging deposunda transfer kayıtlarını tutmak
- DosyaPaylasimi arayüzünü (gonder / al) doldurmak
- Yol güvenliği (sandbox, path traversal, güvenli dosya adı)
- protokol FILE_SHARE yükü üretmek / işlemek (WS sunucu ack ile uyumlu)
- dry_run / bellek içi modda ağ ve disk olmadan test edilebilir olmak
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
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
from sync.arayuzler import DosyaPaylasimi

log = logger_al("sync.files.paylasim")

_KOK = Path(__file__).resolve().parents[2]
_VARSAYILAN_DEPO = _KOK / "data" / "sync" / "files"
_DEPO_SURUM = 1
_VARSAYILAN_MAX_BAYT = 50 * 1024 * 1024  # 50 MiB
_GUVENLI_AD = re.compile(r"^[A-Za-z0-9._\- ()\[\]]+$")


class TransferDurumu(str, Enum):
    """Transfer yaşam döngüsü."""

    BEKLIYOR = "pending"
    HAZIR = "ready"
    TAMAMLANDI = "completed"
    BASARISIZ = "failed"
    IPTAL = "cancelled"


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def varsayilan_depo_yolu() -> Path:
    return _VARSAYILAN_DEPO


def guvenli_dosya_adi(ad: str) -> str:
    """
    Dosya adını path traversal ve tehlikeli karakterlerden arındırır.

    Yalnızca basename kabul edilir; boş / geçersiz adlarda hata.
    """
    ham = (ad or "").strip().replace("\\", "/")
    if not ham:
        raise WhiteCoreError(
            "Dosya adi gerekli",
            kod="SYNC_0010",
            modul="sync.files",
        )
    # Mutlak / üst dizin denemelerini reddet
    if ham.startswith("/") or (len(ham) >= 2 and ham[1] == ":"):
        raise WhiteCoreError(
            "Dosya adinda yol kabul edilmez",
            kod="SYNC_0011",
            modul="sync.files",
            detay={"name": ad},
        )
    if ".." in ham.split("/"):
        raise WhiteCoreError(
            "Path traversal engellendi",
            kod="SYNC_0011",
            modul="sync.files",
            detay={"name": ad},
        )
    base = Path(ham).name
    if not base or base in {".", ".."} or "\x00" in base:
        raise WhiteCoreError(
            "Gecersiz dosya adi",
            kod="SYNC_0011",
            modul="sync.files",
            detay={"name": ad},
        )
    # Çok agresif filtre: izin verilenler dışındakileri '_' yap
    if not _GUVENLI_AD.match(base):
        temiz = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE)
        temiz = temiz.strip(" .")
        if not temiz:
            raise WhiteCoreError(
                "Gecersiz dosya adi",
                kod="SYNC_0011",
                modul="sync.files",
                detay={"name": ad},
            )
        base = temiz
    return base


def sandbox_yolu(
    kok: Path,
    *parcalar: str,
    olustur: bool = False,
) -> Path:
    """
    Kok altına güvenli göreli yol çözer; dışarı çıkmayı engeller.
    """
    kok_r = kok.resolve()
    hedef = kok_r
    for p in parcalar:
        ad = guvenli_dosya_adi(p) if p else ""
        if not ad:
            continue
        hedef = hedef / ad
    hedef_r = hedef.resolve()
    try:
        hedef_r.relative_to(kok_r)
    except ValueError as hata:
        raise WhiteCoreError(
            "Hedef yol sandbox disinda",
            kod="SYNC_0012",
            modul="sync.files",
            detay={"root": str(kok_r), "path": str(hedef)},
        ) from hata
    if olustur:
        hedef_r.parent.mkdir(parents=True, exist_ok=True)
    return hedef_r


def sha256_bayt(veri: bytes) -> str:
    return hashlib.sha256(veri).hexdigest()


def transfer_normalize(ham: dict[str, Any]) -> dict[str, Any]:
    """Gelen sözlüğü kanonik transfer kaydına çevirir."""
    if not isinstance(ham, dict):
        raise WhiteCoreError(
            "Transfer kaydi sozluk olmali",
            kod="SYNC_0013",
            modul="sync.files",
        )
    tid = ham.get("id") or ham.get("transfer_id") or uuid4().hex
    ad = guvenli_dosya_adi(
        str(ham.get("name") or ham.get("ad") or ham.get("filename") or "file.bin")
    )
    durum_ham = ham.get("status") or ham.get("durum") or TransferDurumu.BEKLIYOR.value
    try:
        durum = TransferDurumu(str(durum_ham).lower()).value
    except ValueError:
        durum = TransferDurumu.BEKLIYOR.value
    boyut = ham.get("size") if "size" in ham else ham.get("boyut")
    try:
        boyut_i = int(boyut) if boyut is not None else 0
    except (TypeError, ValueError):
        boyut_i = 0
    if boyut_i < 0:
        boyut_i = 0
    kayit: dict[str, Any] = {
        "id": str(tid),
        "name": ad,
        "size": boyut_i,
        "sha256": str(ham.get("sha256") or ham.get("hash") or ""),
        "status": durum,
        "created": str(ham.get("created") or ham.get("olusturuldu") or _utc_iso()),
        "updated": str(ham.get("updated") or ham.get("guncellendi") or _utc_iso()),
        "direction": str(ham.get("direction") or ham.get("yon") or "outbound"),
        "meta": dict(ham["meta"]) if isinstance(ham.get("meta"), dict) else {},
    }
    cihaz = ham.get("device_id") or ham.get("cihaz_id")
    if cihaz is not None:
        kayit["device_id"] = str(cihaz)
    yerel = ham.get("local_path") or ham.get("yerel_yol")
    if yerel is not None:
        kayit["local_path"] = str(yerel)
    return kayit


@dataclass
class TransferOzet:
    """Son transfer işlem özeti."""

    transfer_id: str = ""
    eklenen: int = 0
    guncellenen: int = 0
    atlanan: int = 0
    toplam: int = 0
    motor: str = "disk"
    dry_run: bool = False
    cihaz_id: Optional[str] = None
    detay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
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
        "transfers": [],
    }
    if not yol.is_file():
        return bos
    try:
        ham = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return bos
    if not isinstance(ham, dict):
        return bos
    liste = ham.get("transfers") or ham.get("transferler") or []
    if not isinstance(liste, list):
        liste = []
    return {
        "version": int(ham.get("version") or _DEPO_SURUM),
        "updated": str(ham.get("updated") or _utc_iso()),
        "transfers": [
            transfer_normalize(x) for x in liste if isinstance(x, dict)
        ],
    }


def _manifest_kaydet(yol: Path, paket: dict[str, Any]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    cikti = {
        "version": int(paket.get("version") or _DEPO_SURUM),
        "updated": _utc_iso(),
        "transfers": list(paket.get("transfers") or []),
    }
    yol.write_text(
        json.dumps(cikti, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class DosyaPaylasim(DosyaPaylasimi, ModulTabani):
    """
    Host dosya paylaşım uygulaması.

    Motorlar:
      - dry_run: disk yazmaz, bellek içi bayt + meta
      - memory / sahte: bellek (zorla_sahte)
      - disk: data/sync/files staging + transfers.json
    """

    ad = "sync.files"
    surum = "0.1.0"
    aciklama = "Cihazlar arasi dosya paylasimi (staging / dry_run)"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        depo_yolu: Optional[Union[str, Path]] = None,
        max_bayt: Optional[int] = None,
    ) -> None:
        ModulTabani.__init__(self)
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.enabled = bool(
            self.ayarlar.al("mobile.features.file_share", True)
        )
        yol = depo_yolu
        if yol is None:
            yol = self.ayarlar.al("sync.files.store_path", None)
        self.depo_yolu = (
            Path(yol).expanduser() if yol else varsayilan_depo_yolu()
        )
        cfg_max = self.ayarlar.al("sync.files.max_bytes", None)
        if max_bayt is not None:
            self.max_bayt = int(max_bayt)
        elif cfg_max is not None:
            self.max_bayt = int(cfg_max)
        else:
            self.max_bayt = _VARSAYILAN_MAX_BAYT

        self._transferler: dict[str, dict[str, Any]] = {}
        self._icerik: dict[str, bytes] = {}  # dry_run / sahte
        self._giden: dict[str, list[str]] = {}  # cihaz → transfer id kuyruğu
        self._motor = self._motor_sec()
        self._yuklendi = False

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise WhiteCoreError(
                "Dosya paylasimi config ile kapali (mobile.features.file_share=false)",
                kod="SYNC_0014",
                modul=self.ad,
            )
        self._motor = self._motor_sec()
        self._yukle()
        if self._motor == "disk" and not self.dry_run:
            self.staging_dizini.mkdir(parents=True, exist_ok=True)
            self.inbox_dizini.mkdir(parents=True, exist_ok=True)
        self._calisiyor = True
        audit_yaz(
            "file_share.started",
            modul=self.ad,
            detay={
                "engine": self._motor,
                "store": str(self.depo_yolu),
                "count": len(self._transferler),
                "max_bytes": self.max_bayt,
            },
        )
        log.info(
            "Dosya paylasimi basladi (motor=%s, kayit=%s)",
            self._motor,
            len(self._transferler),
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        if self._motor == "disk" and not self.dry_run:
            self._kaydet_manifest()
        self._calisiyor = False
        audit_yaz(
            "file_share.stopped",
            modul=self.ad,
            detay={"engine": self._motor, "count": len(self._transferler)},
        )
        log.info("Dosya paylasimi durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ yollar

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def manifest_yolu(self) -> Path:
        return self.depo_yolu / "transfers.json"

    @property
    def staging_dizini(self) -> Path:
        return self.depo_yolu / "staging"

    @property
    def inbox_dizini(self) -> Path:
        return self.depo_yolu / "inbox"

    # ------------------------------------------------------------------ API

    def listele(
        self,
        *,
        cihaz_id: Optional[str] = None,
        durum: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Transfer kayıtlarını filtreleyerek döner."""
        self._ensure_yuklu()
        sonuc: list[dict[str, Any]] = []
        for t in self._transferler.values():
            if cihaz_id is not None and t.get("device_id") != cihaz_id:
                continue
            if durum is not None and t.get("status") != str(durum).lower():
                continue
            sonuc.append(dict(t))
        return sorted(sonuc, key=lambda x: (x.get("created") or "", x["id"]))

    def transfer_al(self, transfer_id: str) -> Optional[dict[str, Any]]:
        self._ensure_yuklu()
        t = self._transferler.get(str(transfer_id))
        return dict(t) if t else None

    async def gonder(
        self,
        cihaz_id: str,
        yerel_yol: str,
        uzak_ad: Optional[str] = None,
    ) -> str:
        """
        Dosyayı staging'e alır ve hedef cihaz kuyruğuna ekler.

        dry_run: içeriği bellekte tutar, disk yazmaz.
        Dönüş: transfer_id
        """
        if not self._calisiyor:
            raise WhiteCoreError(
                "Dosya paylasimi calismiyor; once baslat() cagirin",
                kod="SYNC_0015",
                modul=self.ad,
            )
        cid = str(cihaz_id or "").strip()
        if not cid:
            raise WhiteCoreError(
                "cihaz_id gerekli",
                kod="SYNC_0016",
                modul=self.ad,
            )
        kaynak = Path(yerel_yol).expanduser()
        if not kaynak.is_file():
            raise WhiteCoreError(
                f"Kaynak dosya bulunamadi: {yerel_yol}",
                kod="SYNC_0017",
                modul=self.ad,
                detay={"path": str(kaynak)},
            )
        ad = guvenli_dosya_adi(uzak_ad or kaynak.name)
        veri = kaynak.read_bytes()
        if len(veri) > self.max_bayt:
            raise WhiteCoreError(
                f"Dosya boyutu limiti asildi ({len(veri)} > {self.max_bayt})",
                kod="SYNC_0018",
                modul=self.ad,
                detay={"size": len(veri), "max": self.max_bayt},
            )
        tid = uuid4().hex
        ozet = sha256_bayt(veri)
        yerel_kayit: Optional[str] = None

        if self._motor == "disk" and not self.dry_run:
            hedef = sandbox_yolu(self.staging_dizini, tid, ad, olustur=True)
            hedef.write_bytes(veri)
            yerel_kayit = str(hedef)
        else:
            self._icerik[tid] = veri

        kayit = transfer_normalize(
            {
                "id": tid,
                "name": ad,
                "size": len(veri),
                "sha256": ozet,
                "status": TransferDurumu.HAZIR.value,
                "device_id": cid,
                "direction": "outbound",
                "local_path": yerel_kayit,
            }
        )
        self._transferler[tid] = kayit
        self._giden.setdefault(cid, []).append(tid)
        if self._motor == "disk" and not self.dry_run:
            self._kaydet_manifest()

        audit_yaz(
            "file_share.send",
            modul=self.ad,
            detay={
                "transfer_id": tid,
                "device_id": cid,
                "name": ad,
                "size": len(veri),
                "engine": self._motor,
                "dry_run": self.dry_run,
            },
        )
        log.debug("Dosya gonderildi: %s -> %s (%s bayt)", ad, cid, len(veri))
        return tid

    async def al(self, transfer_id: str, hedef_yol: str) -> str:
        """
        Staging'deki transferi hedef yola yazar.

        dry_run: hedefe yazmaz; planlanan sandbox yolunu döner.
        Dönüş: kaydedilen (veya planlanan) yol.
        """
        if not self._calisiyor:
            raise WhiteCoreError(
                "Dosya paylasimi calismiyor; once baslat() cagirin",
                kod="SYNC_0015",
                modul=self.ad,
            )
        tid = str(transfer_id or "").strip()
        self._ensure_yuklu()
        kayit = self._transferler.get(tid)
        if kayit is None:
            raise WhiteCoreError(
                f"Transfer bulunamadi: {tid}",
                kod="SYNC_0019",
                modul=self.ad,
            )
        if kayit.get("status") == TransferDurumu.IPTAL.value:
            raise WhiteCoreError(
                "Transfer iptal edilmis",
                kod="SYNC_0020",
                modul=self.ad,
                detay={"transfer_id": tid},
            )

        veri = self._icerik_oku(tid, kayit)
        ad = guvenli_dosya_adi(str(kayit.get("name") or "file.bin"))

        # Hedef: boş / dizin → inbox altına güvenli ad; dosya yolu → sandbox veya açık yol
        ham_hedef = (hedef_yol or "").strip()
        if not ham_hedef or ham_hedef in {".", "./"}:
            if self._motor == "disk" and not self.dry_run:
                hedef = sandbox_yolu(self.inbox_dizini, ad, olustur=True)
            else:
                hedef = self.inbox_dizini / ad
        else:
            p = Path(ham_hedef).expanduser()
            if p.suffix == "" and (not p.exists() or p.is_dir()):
                # dizin gibi davran
                if self._motor == "disk" and not self.dry_run:
                    # inbox dışına yazmaya izin: yalnızca açıkça verilen yol
                    # (kullanıcı seçimi); yine de '..' reddedilir
                    self._yol_guvenli_mi(p)
                    hedef = (p / ad).resolve()
                    hedef.parent.mkdir(parents=True, exist_ok=True)
                else:
                    hedef = p / ad
            else:
                self._yol_guvenli_mi(p)
                if self._motor == "disk" and not self.dry_run:
                    hedef = p.resolve()
                    hedef.parent.mkdir(parents=True, exist_ok=True)
                else:
                    hedef = p

        if self.dry_run or self._motor in {"dry_run", "sahte"}:
            kayit["status"] = TransferDurumu.TAMAMLANDI.value
            kayit["updated"] = _utc_iso()
            kayit["local_path"] = str(hedef)
            audit_yaz(
                "file_share.receive",
                modul=self.ad,
                detay={
                    "transfer_id": tid,
                    "path": str(hedef),
                    "dry_run": True,
                    "size": len(veri),
                },
            )
            return str(hedef)

        hedef.write_bytes(veri)
        kayit["status"] = TransferDurumu.TAMAMLANDI.value
        kayit["updated"] = _utc_iso()
        kayit["local_path"] = str(hedef)
        self._kaydet_manifest()
        audit_yaz(
            "file_share.receive",
            modul=self.ad,
            detay={
                "transfer_id": tid,
                "path": str(hedef),
                "dry_run": False,
                "size": len(veri),
            },
        )
        return str(hedef)

    def iptal(self, transfer_id: str) -> dict[str, Any]:
        """Transferi iptal eder; staging içeriğini temizlemeye çalışır."""
        self._ensure_yuklu()
        tid = str(transfer_id)
        kayit = self._transferler.get(tid)
        if kayit is None:
            raise WhiteCoreError(
                f"Transfer bulunamadi: {tid}",
                kod="SYNC_0019",
                modul=self.ad,
            )
        kayit["status"] = TransferDurumu.IPTAL.value
        kayit["updated"] = _utc_iso()
        self._icerik.pop(tid, None)
        if self._motor == "disk" and not self.dry_run:
            stage = self.staging_dizini / tid
            if stage.is_dir():
                shutil.rmtree(stage, ignore_errors=True)
            self._kaydet_manifest()
        audit_yaz(
            "file_share.cancel",
            modul=self.ad,
            detay={"transfer_id": tid},
        )
        return dict(kayit)

    def giden_cek(self, cihaz_id: str) -> list[dict[str, Any]]:
        """Cihaz giden transfer kuyruğunu alıp temizler."""
        ids = self._giden.pop(str(cihaz_id), [])
        sonuc: list[dict[str, Any]] = []
        for tid in ids:
            t = self._transferler.get(tid)
            if t:
                sonuc.append(dict(t))
        return sonuc

    def icerik_al(self, transfer_id: str) -> bytes:
        """Transfer içeriğini bayt olarak döner (test / protokol)."""
        self._ensure_yuklu()
        tid = str(transfer_id)
        kayit = self._transferler.get(tid)
        if kayit is None:
            raise WhiteCoreError(
                f"Transfer bulunamadi: {tid}",
                kod="SYNC_0019",
                modul=self.ad,
            )
        return self._icerik_oku(tid, kayit)

    # ------------------------------------------------------------------ protokol

    def file_share_mesaji(
        self,
        *,
        transfer_id: Optional[str] = None,
        cihaz_id: Optional[str] = None,
        islem: str = "offer",
        icerik_dahil: bool = False,
    ) -> WsMesaj:
        """
        protokol.MesajTipi.FILE_SHARE zarfı üretir.

        payload: {op, transfer?, transfers?, content_b64?}
        """
        self._ensure_yuklu()
        yuk: dict[str, Any] = {"op": islem}
        if transfer_id:
            t = self._transferler.get(str(transfer_id))
            if t is None:
                raise WhiteCoreError(
                    f"Transfer bulunamadi: {transfer_id}",
                    kod="SYNC_0019",
                    modul=self.ad,
                )
            yuk["transfer"] = dict(t)
            if icerik_dahil:
                veri = self._icerik_oku(str(transfer_id), t)
                yuk["content_b64"] = base64.b64encode(veri).decode("ascii")
        else:
            yuk["transfers"] = self.listele(cihaz_id=cihaz_id)
        return mesaj_olustur(MesajTipi.FILE_SHARE, yuk, cihaz_id=cihaz_id)

    def file_share_isle(
        self,
        mesaj: Union[WsMesaj, dict[str, Any]],
        *,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Gelen FILE_SHARE mesajını uygular; sunucu ack detayı ile uyumlu özet.

        op:
          - offer / push / put / apply: uzak dosya meta (+ isteğe bağlı b64) uygula
          - list / pull: transfer listesi
          - get: tek transfer (+ isteğe bağlı içerik)
          - complete: durumu completed yap
          - cancel: iptal
        """
        if isinstance(mesaj, WsMesaj):
            if mesaj.tip is not MesajTipi.FILE_SHARE:
                raise WhiteCoreError(
                    f"Beklenen tip file_share, gelen: {mesaj.tip.value}",
                    kod="SYNC_0021",
                    modul=self.ad,
                )
            yuk = dict(mesaj.yuk)
            cid = cihaz_id or mesaj.cihaz_id
        else:
            yuk = dict(mesaj)
            cid = cihaz_id or yuk.get("device_id") or yuk.get("cihaz_id")

        op = str(yuk.get("op") or yuk.get("islem") or "offer").lower()

        if op in {"list", "pull", "liste"}:
            liste = self.listele(cihaz_id=str(cid) if cid else None)
            return {
                "ok": True,
                "type": MesajTipi.FILE_SHARE.value,
                "op": "list",
                "device_id": cid,
                "transfers": liste,
                "count": len(liste),
            }

        if op == "get":
            tid = str(yuk.get("transfer_id") or yuk.get("id") or "")
            t = self.transfer_al(tid)
            if t is None:
                raise WhiteCoreError(
                    f"Transfer bulunamadi: {tid}",
                    kod="SYNC_0019",
                    modul=self.ad,
                )
            out: dict[str, Any] = {
                "ok": True,
                "type": MesajTipi.FILE_SHARE.value,
                "op": "get",
                "transfer": t,
            }
            if bool(yuk.get("include_content") or yuk.get("icerik_dahil")):
                veri = self.icerik_al(tid)
                out["content_b64"] = base64.b64encode(veri).decode("ascii")
            return out

        if op == "complete":
            tid = str(yuk.get("transfer_id") or yuk.get("id") or "")
            t = self._transferler.get(tid)
            if t is None:
                raise WhiteCoreError(
                    f"Transfer bulunamadi: {tid}",
                    kod="SYNC_0019",
                    modul=self.ad,
                )
            t["status"] = TransferDurumu.TAMAMLANDI.value
            t["updated"] = _utc_iso()
            if self._motor == "disk" and not self.dry_run:
                self._kaydet_manifest()
            return {
                "ok": True,
                "type": MesajTipi.FILE_SHARE.value,
                "op": "complete",
                "transfer": dict(t),
            }

        if op == "cancel":
            t = self.iptal(str(yuk.get("transfer_id") or yuk.get("id") or ""))
            return {
                "ok": True,
                "type": MesajTipi.FILE_SHARE.value,
                "op": "cancel",
                "transfer": t,
            }

        # offer / push / put / apply — inbound staging
        ozet = self._uzak_uygula(yuk, cihaz_id=str(cid) if cid else None)
        return {
            "ok": True,
            "type": MesajTipi.FILE_SHARE.value,
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
            "count": len(self._transferler),
            "max_bytes": self.max_bayt,
            "devices_queued": {k: len(v) for k, v in self._giden.items()},
            "timestamp": _utc_iso(),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "disk"

    def _ensure_yuklu(self) -> None:
        if not self._yuklendi:
            self._yukle()

    def _yukle(self) -> None:
        if self._motor in {"dry_run", "sahte"}:
            if not self._yuklendi:
                self._transferler = {}
                self._icerik = {}
            self._yuklendi = True
            return
        paket = _manifest_yukle(self.manifest_yolu)
        self._transferler = {
            t["id"]: t for t in (paket.get("transfers") or [])
        }
        self._yuklendi = True

    def _kaydet_manifest(self) -> None:
        _manifest_kaydet(
            self.manifest_yolu,
            {
                "version": _DEPO_SURUM,
                "transfers": list(self._transferler.values()),
            },
        )

    def _yol_guvenli_mi(self, yol: Path) -> None:
        """Açık hedef yollarda '..' ve null byte reddi."""
        s = str(yol)
        if "\x00" in s:
            raise WhiteCoreError(
                "Gecersiz yol",
                kod="SYNC_0011",
                modul=self.ad,
            )
        # resolve öncesi parçalarda .. kontrolü
        for parca in Path(s).parts:
            if parca == "..":
                raise WhiteCoreError(
                    "Path traversal engellendi",
                    kod="SYNC_0011",
                    modul=self.ad,
                    detay={"path": s},
                )

    def _icerik_oku(self, tid: str, kayit: dict[str, Any]) -> bytes:
        if tid in self._icerik:
            return self._icerik[tid]
        yerel = kayit.get("local_path")
        if yerel:
            p = Path(str(yerel))
            if p.is_file():
                veri = p.read_bytes()
                if len(veri) > self.max_bayt:
                    raise WhiteCoreError(
                        f"Dosya boyutu limiti asildi ({len(veri)} > {self.max_bayt})",
                        kod="SYNC_0018",
                        modul=self.ad,
                    )
                return veri
        # staging dizininden dene
        if self._motor == "disk":
            stage = self.staging_dizini / tid
            if stage.is_dir():
                adaylar = [x for x in stage.iterdir() if x.is_file()]
                if adaylar:
                    return adaylar[0].read_bytes()
        raise WhiteCoreError(
            f"Transfer icerigi yok: {tid}",
            kod="SYNC_0022",
            modul=self.ad,
        )

    def _uzak_uygula(
        self,
        yuk: dict[str, Any],
        *,
        cihaz_id: Optional[str] = None,
    ) -> TransferOzet:
        """Uzak offer/push yükünü staging'e uygular."""
        self._ensure_yuklu()
        ham_t = yuk.get("transfer") or yuk.get("kayit") or {}
        if not isinstance(ham_t, dict):
            ham_t = {}
        # düz alanlar da kabul
        if not ham_t and (yuk.get("name") or yuk.get("ad") or yuk.get("filename")):
            ham_t = {
                "id": yuk.get("transfer_id") or yuk.get("id"),
                "name": yuk.get("name") or yuk.get("ad") or yuk.get("filename"),
                "size": yuk.get("size") or yuk.get("boyut"),
                "sha256": yuk.get("sha256") or yuk.get("hash"),
                "device_id": cihaz_id,
            }
        if not ham_t:
            raise WhiteCoreError(
                "FILE_SHARE yukunde transfer bilgisi yok",
                kod="SYNC_0023",
                modul=self.ad,
            )
        if cihaz_id:
            ham_t.setdefault("device_id", cihaz_id)
        ham_t.setdefault("direction", "inbound")

        b64 = yuk.get("content_b64") or yuk.get("icerik_b64")
        veri: Optional[bytes] = None
        if isinstance(b64, str) and b64:
            try:
                veri = base64.b64decode(b64, validate=True)
            except Exception as hata:
                raise WhiteCoreError(
                    "content_b64 cozulemedi",
                    kod="SYNC_0024",
                    modul=self.ad,
                ) from hata
            if len(veri) > self.max_bayt:
                raise WhiteCoreError(
                    f"Dosya boyutu limiti asildi ({len(veri)} > {self.max_bayt})",
                    kod="SYNC_0018",
                    modul=self.ad,
                )
            ham_t["size"] = len(veri)
            ham_t["sha256"] = sha256_bayt(veri)

        kayit = transfer_normalize(ham_t)
        tid = kayit["id"]
        onceki = self._transferler.get(tid)
        eklenen = 0
        guncellenen = 0
        if onceki is None:
            eklenen = 1
        else:
            guncellenen = 1

        yerel_kayit: Optional[str] = None
        if veri is not None:
            if self._motor == "disk" and not self.dry_run:
                hedef = sandbox_yolu(
                    self.staging_dizini, tid, kayit["name"], olustur=True
                )
                hedef.write_bytes(veri)
                yerel_kayit = str(hedef)
            else:
                self._icerik[tid] = veri
            kayit["status"] = TransferDurumu.HAZIR.value
            kayit["local_path"] = yerel_kayit
        else:
            kayit["status"] = TransferDurumu.BEKLIYOR.value

        self._transferler[tid] = kayit
        if self._motor == "disk" and not self.dry_run:
            self._kaydet_manifest()

        ozet = TransferOzet(
            transfer_id=tid,
            eklenen=eklenen,
            guncellenen=guncellenen,
            atlanan=0,
            toplam=len(self._transferler),
            motor=self._motor,
            dry_run=self.dry_run,
            cihaz_id=cihaz_id,
            detay={
                "name": kayit["name"],
                "size": kayit["size"],
                "has_content": veri is not None,
            },
        )
        audit_yaz("file_share.apply", modul=self.ad, detay=ozet.to_dict())
        return ozet


__all__ = [
    "DosyaPaylasim",
    "TransferDurumu",
    "TransferOzet",
    "varsayilan_depo_yolu",
    "guvenli_dosya_adi",
    "sandbox_yolu",
    "transfer_normalize",
    "sha256_bayt",
]
