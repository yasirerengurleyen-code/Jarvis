"""
vision/yuz/kayit.py
-------------------
Çoklu kullanıcı yüz kaydı (LOCAL ONLY).

Görev:
- Yerel diskte kullanıcı kaydı / listeleme / silme
- Minimal yüz profili (embedding / şablon yalnızca yerel)
- YuzGizlilikYoneticisi zorunlu: toggle + kamera izni
- Wire / audit'te embedding / şablon yok
- Bulut / sync / harici API yok

Depolama (varsayılan kök: gizlilik.yerel_kok → database/faces):
  {kok}/users.json
  {kok}/templates/{user_id}.bin   (opsiyonel şablon baytı)
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    KayitliKullanici,
    YuzGizlilikPolitikasi,
    kayitli_kullanici_olustur,
)
from vision.yuz.gizlilik import (
    YuzGizlilikYoneticisi,
    wire_temizle,
    yuz_gizlilik_olustur,
)

log = logger_al("vision.yuz.kayit")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_YUZ_KAYIT_BASLADI = "vision.face.registry.started"
OLAY_YUZ_KAYIT_DURDU = "vision.face.registry.stopped"
OLAY_YUZ_KAYDEDILDI = "vision.face.registry.registered"
OLAY_YUZ_SILINDI = "vision.face.registry.removed"
OLAY_YUZ_LISTELENDI = "vision.face.registry.listed"

# Yerel indeks dosyası
_INDEKS_DOSYA = "users.json"
_SABLON_KLASOR = "templates"
_INDEKS_SURUM = 1

# Kullanıcı adı: boşluk / harf / rakam / Türkçe karakter / _.-
_AD_DESEN = re.compile(r"^[\w.\- ]+$", re.UNICODE)


class YuzKayitYoneticisi(ModulTabani):
    """
    Yerel çoklu kullanıcı yüz kayıt yöneticisi.

    1) Gizlilik izni yoksa → VisionError (kayıt/liste/silme yok)
    2) dry_run → bellek içi kayıt (disk yazılmaz)
    3) Aksi halde kullanıcılar yerel users.json (+ opsiyonel şablon) içinde
    """

    ad = "vision.yuz.kayit"
    surum = "0.1.0"
    aciklama = "Yüz kayıt — çoklu kullanıcı, yerel disk, gizlilik kapılı"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        gizlilik: Optional[YuzGizlilikYoneticisi] = None,
        yerel_kok: Optional[Union[str, Path]] = None,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.olay_yayinla = bool(olay_yayinla)
        self._kilit = threading.RLock()
        self._bellek: dict[str, KayitliKullanici] = {}
        self._yuklendi = False

        if gizlilik is not None:
            self.gizlilik = gizlilik
            if yerel_kok is not None:
                # Kayıt kökü gizlilik üzerinden tutarlı kalsın
                self.gizlilik._yerel_kok_arg = Path(yerel_kok)  # noqa: SLF001
        else:
            self.gizlilik = yuz_gizlilik_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                olay_yayinla=False,
                kamera_izin=True if self.dry_run else None,
                yuz_aktif=True if self.dry_run else None,
                yerel_kok=yerel_kok,
            )

        self._log = logger_al(f"modul.{self.ad}")
        self._son_kayit: Optional[KayitliKullanici] = None

    # ------------------------------------------------------------------ özellik

    @property
    def yerel_kok(self) -> Path:
        """Yüz profillerinin tutulduğu yerel kök."""
        return self.gizlilik.yerel_kok()

    @property
    def indeks_yolu(self) -> Path:
        return self.yerel_kok / _INDEKS_DOSYA

    @property
    def sablon_kok(self) -> Path:
        return self.yerel_kok / _SABLON_KLASOR

    @property
    def son_kayit(self) -> Optional[KayitliKullanici]:
        return self._son_kayit

    def ozet(self) -> dict[str, Any]:
        with self._kilit:
            self._yukle_gerekirse()
            adet = len(self._bellek)
        return {
            "name": self.ad,
            "version": self.surum,
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "local_only": True,
            "cloud_allowed": False,
            "dry_run": bool(self.dry_run),
            "storage_root": str(self.yerel_kok),
            "index_path": str(self.indeks_yolu),
            "user_count": int(adet),
            "face_enabled": self.gizlilik.yuz_tanima_aktif_mi(),
            "camera_permission": self.gizlilik.kamera_izni_var_mi(),
            "running": bool(self._calisiyor),
            "last_user_id": self._son_kayit.id if self._son_kayit else None,
        }

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001
                pass
        if not self.gizlilik.calisiyor:
            try:
                await self.gizlilik.baslat()
            except Exception as hata:  # noqa: BLE001
                self._log.debug("Gizlilik baslat atlandi: %s", hata)
        with self._kilit:
            self._yukle_gerekirse()
        self._isaret_basladi()
        detay = self._audit_detay({"engine": "registry", "user_count": self.say(izin_zorla=False)})
        self._audit("vision.face.registry.started", detay)
        self._yayin(OLAY_YUZ_KAYIT_BASLADI, detay)
        self._log.info(
            "Yuz kayit basladi dry_run=%s kok=%s adet=%s",
            self.dry_run,
            self.yerel_kok,
            detay.get("user_count"),
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        detay = self._audit_detay({"engine": "registry"})
        self._audit("vision.face.registry.stopped", detay)
        self._yayin(OLAY_YUZ_KAYIT_DURDU, detay)
        self._log.info("Yuz kayit durdu")

    # ------------------------------------------------------------------ izin

    def izin_kontrol(self) -> None:
        """
        Kayıt işlemleri tanıma kapsamındadır: toggle + kamera izni zorunlu.
        """
        self.gizlilik.izin_zorla(tanima_gerekli=True)

    def izinli_mi(self) -> bool:
        return self.gizlilik.islem_izinli_mi(tanima_gerekli=True)

    # ------------------------------------------------------------------ API

    def kaydet(
        self,
        gorunen_ad: str,
        *,
        embedding: Optional[Sequence[float]] = None,
        sablon: Optional[bytes] = None,
        sablon_yolu: Optional[Union[str, Path]] = None,
        kullanici_id: Optional[str] = None,
        izin_zorla: bool = True,
    ) -> KayitliKullanici:
        """
        Yeni kullanıcıyı yerel olarak kaydeder.

        embedding / sablon yalnızca yerel diskte (veya dry_run bellekte) tutulur.
        Wire olayında şablon yok.
        """
        if izin_zorla:
            self.izin_kontrol()

        ad = (gorunen_ad or "").strip()
        if not ad:
            raise VisionError(
                "gorunen_ad bos olamaz",
                kod="VIS_0721",
                modul=self.ad,
            )
        if not _AD_DESEN.match(ad) or len(ad) > 80:
            raise VisionError(
                f"Gecersiz gorunen_ad: {gorunen_ad!r}",
                kod="VIS_0721",
                modul=self.ad,
                detay={"display_name": gorunen_ad},
            )

        emb = [float(x) for x in embedding] if embedding is not None else None
        sablon_rel: Optional[str] = None

        with self._kilit:
            self._yukle_gerekirse()
            # Aynı görünen ad (büyük/küçük duyarsız) yasak
            anahtar = ad.casefold()
            for k in self._bellek.values():
                if k.aktif and (k.gorunen_ad or "").strip().casefold() == anahtar:
                    raise VisionError(
                        f"Bu gorunen_ad zaten kayitli: {ad}",
                        kod="VIS_0724",
                        modul=self.ad,
                        detay={"display_name": ad, "user_id": k.id},
                    )

            kullanici = kayitli_kullanici_olustur(
                ad,
                embedding=emb,
                sablon_yolu=str(sablon_yolu) if sablon_yolu else None,
            )
            if kullanici_id:
                kullanici.id = str(kullanici_id).strip() or kullanici.id

            if sablon is not None and not self.dry_run:
                sablon_rel = self._sablon_yaz(kullanici.id, bytes(sablon))
                kullanici.sablon_yolu = sablon_rel
            elif sablon is not None and self.dry_run:
                # dry_run: yolu işaretle, dosya yazma
                kullanici.sablon_yolu = f"{_SABLON_KLASOR}/{kullanici.id}.bin"

            self._bellek[kullanici.id] = kullanici
            if not self.dry_run:
                self._diske_yaz()
            self._son_kayit = kullanici

        detay = self._audit_detay(
            {
                "user_id": kullanici.id,
                "display_name": kullanici.gorunen_ad,
                "has_embedding": emb is not None,
                "has_template": bool(kullanici.sablon_yolu),
                "dry_run": bool(self.dry_run),
            }
        )
        self._audit("vision.face.registry.registered", detay)
        self._yayin(OLAY_YUZ_KAYDEDILDI, self.gizlilik.wire_icin(kullanici))
        self._log.info(
            "Yuz kullanici kaydedildi id=%s ad=%s dry_run=%s",
            kullanici.id,
            kullanici.gorunen_ad,
            self.dry_run,
        )
        return kullanici

    def listele(
        self,
        *,
        sadece_aktif: bool = True,
        wire: bool = False,
        izin_zorla: bool = True,
    ) -> list[Any]:
        """
        Kayıtlı kullanıcıları listeler.

        wire=True → embedding / şablon yolu olmayan dict listesi.
        """
        if izin_zorla:
            self.izin_kontrol()

        with self._kilit:
            self._yukle_gerekirse()
            kullanicilar = [
                k
                for k in self._bellek.values()
                if (k.aktif if sadece_aktif else True)
            ]
            # Kararlı sıra: oluşturma + id
            kullanicilar.sort(key=lambda k: (k.olusturma or "", k.id))

        detay = self._audit_detay(
            {"count": len(kullanicilar), "wire": bool(wire), "active_only": sadece_aktif}
        )
        self._audit("vision.face.registry.listed", detay)
        self._yayin(
            OLAY_YUZ_LISTELENDI,
            wire_temizle({"count": len(kullanicilar), "local_only": True}),
        )

        if wire:
            return [self.gizlilik.wire_icin(k) for k in kullanicilar]
        return list(kullanicilar)

    def getir(
        self,
        kullanici_id: str,
        *,
        izin_zorla: bool = True,
    ) -> Optional[KayitliKullanici]:
        """ID ile kullanıcı getirir (yoksa None)."""
        if izin_zorla:
            self.izin_kontrol()
        kid = (kullanici_id or "").strip()
        if not kid:
            return None
        with self._kilit:
            self._yukle_gerekirse()
            k = self._bellek.get(kid)
            return k

    def getir_ad(
        self,
        gorunen_ad: str,
        *,
        izin_zorla: bool = True,
    ) -> Optional[KayitliKullanici]:
        """Görünen ada göre (casefold) aktif kullanıcı."""
        if izin_zorla:
            self.izin_kontrol()
        ad = (gorunen_ad or "").strip().casefold()
        if not ad:
            return None
        with self._kilit:
            self._yukle_gerekirse()
            for k in self._bellek.values():
                if k.aktif and (k.gorunen_ad or "").strip().casefold() == ad:
                    return k
        return None

    def sil(
        self,
        kullanici_id: str,
        *,
        izin_zorla: bool = True,
    ) -> bool:
        """
        Kullanıcıyı yerel kayıttan siler (şablon dosyası da temizlenir).

        Yoksa False; izin yoksa VisionError.
        """
        if izin_zorla:
            self.izin_kontrol()

        kid = (kullanici_id or "").strip()
        if not kid:
            raise VisionError(
                "kullanici_id bos olamaz",
                kod="VIS_0722",
                modul=self.ad,
            )

        with self._kilit:
            self._yukle_gerekirse()
            kullanici = self._bellek.pop(kid, None)
            if kullanici is None:
                return False
            if not self.dry_run:
                self._sablon_sil(kullanici)
                self._diske_yaz()
            if self._son_kayit and self._son_kayit.id == kid:
                self._son_kayit = None

        detay = self._audit_detay(
            {
                "user_id": kid,
                "display_name": kullanici.gorunen_ad,
                "removed": True,
            }
        )
        self._audit("vision.face.registry.removed", detay)
        self._yayin(
            OLAY_YUZ_SILINDI,
            wire_temizle(
                {
                    "user_id": kid,
                    "display_name": kullanici.gorunen_ad,
                    "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
                    "local_only": True,
                }
            ),
        )
        self._log.info("Yuz kullanici silindi id=%s", kid)
        return True

    def say(self, *, sadece_aktif: bool = True, izin_zorla: bool = True) -> int:
        """Kayıtlı kullanıcı sayısı."""
        return len(
            self.listele(sadece_aktif=sadece_aktif, wire=False, izin_zorla=izin_zorla)
        )

    def wire_liste(self, *, sadece_aktif: bool = True, izin_zorla: bool = True) -> list[dict[str, Any]]:
        """Wire-güvenli kullanıcı listesi (embedding yok)."""
        return self.listele(sadece_aktif=sadece_aktif, wire=True, izin_zorla=izin_zorla)  # type: ignore[return-value]

    def buluta_gonder(self, veri: Any = None) -> None:
        """Yüz kayıt verisi asla buluta gitmez."""
        self.gizlilik.bulut_gonderimini_engelle(veri)

    # ------------------------------------------------------------------ iç — depolama

    def _yukle_gerekirse(self) -> None:
        if self._yuklendi:
            return
        if self.dry_run:
            self._yuklendi = True
            return
        self._diskten_yukle()
        self._yuklendi = True

    def _diskten_yukle(self) -> None:
        yol = self.indeks_yolu
        if not yol.is_file():
            self._bellek = {}
            return
        try:
            ham = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as hata:
            raise VisionError(
                f"Yuz kayit indeksi okunamadi: {yol}",
                kod="VIS_0723",
                modul=self.ad,
                detay={"path": str(yol), "error": str(hata)},
            ) from hata

        kullanicilar_ham = ham.get("users") if isinstance(ham, dict) else None
        if not isinstance(kullanicilar_ham, list):
            self._bellek = {}
            return

        yeni: dict[str, KayitliKullanici] = {}
        for item in kullanicilar_ham:
            if not isinstance(item, dict):
                continue
            try:
                k = KayitliKullanici.from_dict(item)
            except Exception as hata:  # noqa: BLE001
                self._log.warning("Bozuk kullanici kaydi atlandi: %s", hata)
                continue
            yeni[k.id] = k
        self._bellek = yeni

    def _diske_yaz(self) -> None:
        """Bellekteki profilleri yerel users.json'a yazar (embedding dahil)."""
        try:
            kok = self.gizlilik.yerel_kok_hazirla()
        except VisionError:
            raise
        paket = {
            "v": _INDEKS_SURUM,
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "local_only": True,
            "storage": "local",
            "users": [k.to_dict(wire=False) for k in self._bellek.values()],
        }
        hedef = kok / _INDEKS_DOSYA
        tmp = hedef.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(paket, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(hedef)
        except OSError as hata:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass
            raise VisionError(
                f"Yuz kayit indeksi yazilamadi: {hedef}",
                kod="VIS_0723",
                modul=self.ad,
                detay={"path": str(hedef), "error": str(hata)},
            ) from hata

    def _sablon_yaz(self, kullanici_id: str, veri: bytes) -> str:
        """Şablon baytını yerel templates/ altına yazar; göreli yol döner."""
        try:
            self.gizlilik.yerel_kok_hazirla()
            klasor = self.sablon_kok
            klasor.mkdir(parents=True, exist_ok=True)
            yol = klasor / f"{kullanici_id}.bin"
            yol.write_bytes(veri)
        except OSError as hata:
            raise VisionError(
                f"Yuz sablonu yazilamadi: {kullanici_id}",
                kod="VIS_0723",
                modul=self.ad,
                detay={"user_id": kullanici_id, "error": str(hata)},
            ) from hata
        # Göreli yol (kök altında) — taşınabilirlik
        return f"{_SABLON_KLASOR}/{kullanici_id}.bin"

    def _sablon_sil(self, kullanici: KayitliKullanici) -> None:
        yollar: list[Path] = []
        if kullanici.sablon_yolu:
            p = Path(kullanici.sablon_yolu)
            if not p.is_absolute():
                p = self.yerel_kok / p
            yollar.append(p)
        yollar.append(self.sablon_kok / f"{kullanici.id}.bin")
        for yol in yollar:
            try:
                if yol.is_file():
                    yol.unlink()
            except OSError as hata:
                self._log.debug("Sablon silinemedi %s: %s", yol, hata)

    # ------------------------------------------------------------------ iç — olay / audit

    def _audit_detay(self, ekstra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        temel = self.gizlilik.audit_icin(
            {
                "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
                "local_only": True,
                "storage_root": str(self.yerel_kok),
                "dry_run": bool(self.dry_run),
            }
        )
        if ekstra:
            temel.update(wire_temizle(dict(ekstra)))
        return wire_temizle(temel)

    def _yayin(self, olay: str, veri: Mapping[str, Any]) -> None:
        if not self.olay_yayinla or self.bus is None:
            return
        try:
            self.bus.publish_sync(olay, wire_temizle(dict(veri)), kaynak=self.ad)
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Olay yayinlanamadi %s: %s", olay, hata)

    def _audit(self, olay: str, detay: Mapping[str, Any]) -> None:
        try:
            audit_yaz(olay, modul=self.ad, detay=wire_temizle(dict(detay)))
        except Exception as hata:  # noqa: BLE001
            self._log.debug("Audit yazilamadi %s: %s", olay, hata)


def yuz_kayit_olustur(
    *,
    dry_run: bool = True,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    yerel_kok: Optional[Union[str, Path]] = None,
    olay_yayinla: bool = False,
    kamera_izin: Optional[bool] = True,
    yuz_aktif: Optional[bool] = True,
) -> YuzKayitYoneticisi:
    """Test / demo için güvenli varsayılanlarla YuzKayitYoneticisi üretir."""
    g = gizlilik
    if g is None:
        g = yuz_gizlilik_olustur(
            ayarlar=ayarlar,
            bus=bus,
            dry_run=dry_run,
            olay_yayinla=False,
            kamera_izin=kamera_izin,
            yuz_aktif=yuz_aktif,
            yerel_kok=yerel_kok,
        )
    return YuzKayitYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        gizlilik=g,
        yerel_kok=yerel_kok,
        olay_yayinla=olay_yayinla,
    )


def yuz_kullanici_kaydet(
    gorunen_ad: str,
    *,
    embedding: Optional[Sequence[float]] = None,
    sablon: Optional[bytes] = None,
    dry_run: bool = False,
    yerel_kok: Optional[Union[str, Path]] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    kamera_izin: bool = True,
    yuz_aktif: bool = True,
) -> KayitliKullanici:
    """Tek çağrılık yerel kullanıcı kayıt yardımcısı."""
    y = yuz_kayit_olustur(
        dry_run=dry_run,
        yerel_kok=yerel_kok,
        gizlilik=gizlilik,
        kamera_izin=kamera_izin,
        yuz_aktif=yuz_aktif,
        olay_yayinla=False,
    )
    return y.kaydet(gorunen_ad, embedding=embedding, sablon=sablon)


__all__ = [
    "OLAY_YUZ_KAYIT_BASLADI",
    "OLAY_YUZ_KAYIT_DURDU",
    "OLAY_YUZ_KAYDEDILDI",
    "OLAY_YUZ_SILINDI",
    "OLAY_YUZ_LISTELENDI",
    "YuzKayitYoneticisi",
    "yuz_kayit_olustur",
    "yuz_kullanici_kaydet",
]
