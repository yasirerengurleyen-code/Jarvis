"""
vision/yoneticisi.py
--------------------
Vision Manager — kamera / OCR / analiz / yüz / Vision AI orkestrasyonu.

Görev:
- Alt motorları (camera, ocr, analiz, yuz, ai) birleştirmek
- start/stop yaşam döngüsü ve facade API sağlamak
- EventBus + Logger/audit + Config + VisionError kalıpları
- Yüz gizliliği: local-only, ayarlar toggle, izin kontrolleri
- dry_run / sahte modda donanım / OpenCV olmadan test edilebilmek

Not: Engine yaşam döngüsü köprüsü `core/engine.py` + `config.vision`
üzerinden yapılır; bu sınıf Vision runtime facade'ıdır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.ai.aciklama import GorselAciklama, gorsel_aciklama_olustur
from vision.ai.multimodal import MultimodalAnaliz, multimodal_analiz_olustur
from vision.ai.sayma import NesneSayici, nesne_sayici_olustur
from vision.ai.soru_cevap import GorselSoruCevap, gorsel_soru_cevap_olustur
from vision.analiz.nesne import NesneAlgilayici, nesne_algilayici_olustur
from vision.analiz.qr import QrAnalizci, qr_analizci_olustur
from vision.analiz.renk import RenkAnalizci, renk_analizci_olustur
from vision.analiz.sahne import SahneAnalizci, sahne_analizci_olustur
from vision.camera.akis import VideoAkis, video_akis_olustur
from vision.camera.kamera import KameraYoneticisi, kamera_yoneticisi_olustur
from vision.modeller import (
    AnalizSonucu,
    KameraAyarlari,
    KameraCihazi,
    Kare,
    KayitliKullanici,
    OcrSonucu,
    VisionAiSonucu,
    YakalamaSonucu,
    YuzKutusu,
    YuzTanimaSonucu,
)
from vision.ocr.ekran import EkranOcr, ekran_ocr_olustur
from vision.ocr.motor import OcrYoneticisi, ocr_yoneticisi_olustur
from vision.ocr.pdf import PdfOcr, pdf_ocr_olustur
from vision.yuz.algilama import YuzAlgilamaSonucu, YuzAlgilayici, yuz_algilayici_olustur
from vision.yuz.gizlilik import YuzGizlilikYoneticisi, yuz_gizlilik_olustur
from vision.yuz.kayit import YuzKayitYoneticisi, yuz_kayit_olustur
from vision.yuz.tanima import YuzTaniyici, yuz_taniyici_olustur

log = logger_al("vision.yoneticisi")

# EventBus olay adları (wire İngilizce stil)
OLAY_VISION_BASLADI = "vision.started"
OLAY_VISION_DURDU = "vision.stopped"

GirdiTuru = Any
BolgeTuru = Any
PdfGirdi = Union[str, Path]


class VisionYoneticisi(ModulTabani):
    """
    J.A.R.V.I.S. Vision yöneticisi (host tarafı facade).

    Alt bileşenler:
      kamera / akis → ocr / ekran / pdf → nesne / sahne / renk / qr
      → gizlilik / algilama / kayit / tanima → aciklama / vqa / sayma / multimodal
    """

    ad = "vision"
    surum = "0.1.0"
    aciklama = "Vision Manager — kamera / OCR / analiz / yüz / Vision AI"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        olustur: bool = True,
        olay_yayinla: bool = True,
        # Kamera
        kamera: Optional[KameraYoneticisi] = None,
        akis: Optional[VideoAkis] = None,
        cihaz: Optional[int] = None,
        fps: Optional[int] = None,
        # OCR
        ocr: Optional[OcrYoneticisi] = None,
        ekran: Optional[EkranOcr] = None,
        pdf: Optional[PdfOcr] = None,
        # Analiz
        nesne: Optional[NesneAlgilayici] = None,
        sahne: Optional[SahneAnalizci] = None,
        renk: Optional[RenkAnalizci] = None,
        qr: Optional[QrAnalizci] = None,
        # Yüz
        gizlilik: Optional[YuzGizlilikYoneticisi] = None,
        algilama: Optional[YuzAlgilayici] = None,
        kayit: Optional[YuzKayitYoneticisi] = None,
        tanima: Optional[YuzTaniyici] = None,
        yuz_aktif: Optional[bool] = None,
        kamera_izin: Optional[bool] = None,
        yerel_kok: Optional[Union[str, Path]] = None,
        # Vision AI
        aciklama: Optional[GorselAciklama] = None,
        vqa: Optional[GorselSoruCevap] = None,
        sayma: Optional[NesneSayici] = None,
        multimodal: Optional[MultimodalAnaliz] = None,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)

        self.enabled = bool(self.ayarlar.al("vision.enabled", True))

        # --- alt örnekler (enjekte veya fabrika) ---
        self.kamera = kamera
        self.akis = akis
        self.ocr = ocr
        self.ekran = ekran
        self.pdf = pdf
        self.nesne = nesne
        self.sahne = sahne
        self.renk = renk
        self.qr = qr
        self.gizlilik = gizlilik
        self.algilama = algilama
        self.kayit = kayit
        self.tanima = tanima
        self.aciklama = aciklama
        self.vqa = vqa
        self.sayma = sayma
        self.multimodal = multimodal

        if olustur:
            self._altlari_olustur(
                cihaz=cihaz,
                fps=fps,
                yuz_aktif=yuz_aktif,
                kamera_izin=kamera_izin,
                yerel_kok=yerel_kok,
            )

        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ fabrika yardımcı

    def _altlari_olustur(
        self,
        *,
        cihaz: Optional[int],
        fps: Optional[int],
        yuz_aktif: Optional[bool],
        kamera_izin: Optional[bool],
        yerel_kok: Optional[Union[str, Path]],
    ) -> None:
        """Eksik alt motorları dry_run-dostu fabrikalarla üretir; paylaşımlı bağlar."""
        ortak = dict(
            ayarlar=self.ayarlar,
            bus=self.bus,
            dry_run=self.dry_run,
            olay_yayinla=False,  # üst yönetici olayları yayınlar
        )
        ortak_sahte = {**ortak, "zorla_sahte": self.zorla_sahte}

        # Kamera + akış (aynı KameraYoneticisi)
        if self.kamera is None:
            self.kamera = kamera_yoneticisi_olustur(
                cihaz=int(cihaz if cihaz is not None else 0),
                fps=int(fps if fps is not None else 15),
                **ortak_sahte,
            )
        if self.akis is None:
            self.akis = video_akis_olustur(
                kamera=self.kamera,
                kamera_yonet=True,
                olay_yayinla=False,
                bus=self.bus,
                dry_run=self.dry_run,
                zorla_sahte=self.zorla_sahte,
            )

        # OCR ailesi (ortak OcrYoneticisi)
        if self.ocr is None:
            self.ocr = ocr_yoneticisi_olustur(**ortak_sahte)
        if self.ekran is None:
            self.ekran = ekran_ocr_olustur(ocr=self.ocr, **ortak_sahte)
        if self.pdf is None:
            self.pdf = pdf_ocr_olustur(ocr=self.ocr, **ortak_sahte)

        # Görsel analiz
        if self.nesne is None:
            self.nesne = nesne_algilayici_olustur(**ortak_sahte)
        if self.sahne is None:
            self.sahne = sahne_analizci_olustur(**ortak_sahte)
        if self.renk is None:
            self.renk = renk_analizci_olustur(**ortak_sahte)
        if self.qr is None:
            self.qr = qr_analizci_olustur(**ortak_sahte)

        # Yüz — tek gizlilik örneği; varsayılan toggle kapalı (config)
        # dry_run'da kamera izni True (offline test); yuz_aktif config'e bağlı
        if self.gizlilik is None:
            izin = kamera_izin
            if izin is None and self.dry_run:
                izin = True
            self.gizlilik = yuz_gizlilik_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                olay_yayinla=False,
                yuz_aktif=yuz_aktif,
                kamera_izin=izin,
                yerel_kok=yerel_kok,
            )
        if self.algilama is None:
            self.algilama = yuz_algilayici_olustur(
                gizlilik=self.gizlilik,
                **ortak_sahte,
            )
        if self.kayit is None:
            self.kayit = yuz_kayit_olustur(
                gizlilik=self.gizlilik,
                yerel_kok=yerel_kok,
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                olay_yayinla=False,
            )
        if self.tanima is None:
            self.tanima = yuz_taniyici_olustur(
                gizlilik=self.gizlilik,
                kayit=self.kayit,
                algilayici=self.algilama,
                **ortak_sahte,
            )

        # Vision AI
        if self.aciklama is None:
            self.aciklama = gorsel_aciklama_olustur(**ortak_sahte)
        if self.vqa is None:
            self.vqa = gorsel_soru_cevap_olustur(**ortak_sahte)
        if self.sayma is None:
            self.sayma = nesne_sayici_olustur(**ortak_sahte)
        if self.multimodal is None:
            self.multimodal = multimodal_analiz_olustur(**ortak_sahte)

    # ------------------------------------------------------------------ yaşam

    async def baslat(self) -> None:
        if self._calisiyor:
            return
        if not self.ayarlar.yuklendi:
            try:
                self.ayarlar.yukle()
            except Exception:  # noqa: BLE001 — test / bellek ayarları
                pass

        self.enabled = bool(self.ayarlar.al("vision.enabled", True))
        if not self.enabled and not self.dry_run and not self.zorla_sahte:
            raise VisionError(
                "Vision config ile kapali (vision.enabled=false)",
                kod="VIS_0050",
                modul=self.ad,
            )

        self._motor = self._motor_sec()

        # Sıra: gizlilik → kamera → OCR → analiz → yüz → AI
        # Akış kamera oturumuna bağlanır; kamera_yonet dış kamerayı kapatmaz.
        for ad, modul in self._yasam_modulleri():
            if modul is None:
                continue
            try:
                await modul.baslat()
            except Exception as exc:  # noqa: BLE001
                log.warning("Vision alt modul baslatilamadi (%s): %s", ad, exc)
                raise VisionError(
                    f"Vision alt modul baslatilamadi ({ad}): {exc}",
                    kod="VIS_0052",
                    modul=self.ad,
                    detay={"component": ad, "error": str(exc)},
                ) from exc

        # VideoAkis: kamera zaten açık; yalnızca akış bayrağı
        if self.akis is not None:
            try:
                await self.akis.baslat()
            except Exception as exc:  # noqa: BLE001
                log.warning("Video akis baslatilamadi: %s", exc)

        self._isaret_basladi()
        detay = {
            "engine": self._motor,
            "dry_run": self.dry_run,
            "face_enabled": (
                self.gizlilik.yuz_tanima_aktif_mi() if self.gizlilik else False
            ),
            "local_only": True,
            "camera": getattr(self.kamera, "motor", None),
            "ocr": getattr(self.ocr, "motor", None),
        }
        audit_yaz("vision.started", modul=self.ad, detay=detay)
        await self._yayin(OLAY_VISION_BASLADI, detay)
        log.info(
            "Vision Manager hazir (motor=%s, face=%s, kamera=%s)",
            self._motor,
            detay["face_enabled"],
            detay["camera"],
        )

    async def durdur(self) -> None:
        if not self._calisiyor:
            return

        # Ters sıra
        if self.akis is not None:
            try:
                await self.akis.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("Video akis durdurma: %s", exc)

        for ad, modul in reversed(self._yasam_modulleri()):
            if modul is None:
                continue
            try:
                await modul.durdur()
            except Exception as exc:  # noqa: BLE001
                log.warning("Vision alt modul durdurma (%s): %s", ad, exc)

        self._isaret_durdu()
        detay = {"engine": self._motor}
        audit_yaz("vision.stopped", modul=self.ad, detay=detay)
        await self._yayin(OLAY_VISION_DURDU, detay)
        log.info("Vision Manager durduruldu (motor=%s)", self._motor)

    # ------------------------------------------------------------------ özellikler

    @property
    def motor(self) -> str:
        return self._motor

    def yuz_tanima_aktif_mi(self) -> bool:
        """Yüz tanıma ayarlar toggle (local-only politika)."""
        if self.gizlilik is None:
            return False
        return self.gizlilik.yuz_tanima_aktif_mi()

    def yuz_tanima_ayarla(self, aktif: bool) -> bool:
        """Yüz tanımayı runtime'da aç/kapa (config dosyasına yazmaz)."""
        g = self._gizlilik_gerekli()
        return g.yuz_tanima_ayarla(bool(aktif))

    def kamera_izni_ayarla(self, izin: bool) -> bool:
        """Kamera iznini runtime'da ayarlar."""
        g = self._gizlilik_gerekli()
        return g.kamera_izni_ayarla(bool(izin))

    def kamera_izni_var_mi(self) -> bool:
        """Kamera izni (runtime override dahil)."""
        if self.gizlilik is None:
            return True
        return bool(self.gizlilik.kamera_izni_var_mi())

    # ------------------------------------------------------------------ kamera facade

    def kamera_listele(self, *, max_indeks: int = 5) -> list[KameraCihazi]:
        self._calisiyor_mi()
        return self._kamera_gerekli().cihazlari_listele(max_indeks=max_indeks)

    def kamera_sec(self, indeks: int) -> KameraAyarlari:
        self._calisiyor_mi()
        return self._kamera_gerekli().cihaz_sec(indeks)

    def fps_ayarla(self, fps: int) -> KameraAyarlari:
        self._calisiyor_mi()
        return self._kamera_gerekli().fps_ayarla(fps)

    def fotograf_cek(self, *, yol: Optional[Union[str, Path]] = None) -> YakalamaSonucu:
        self._calisiyor_mi()
        return self._kamera_gerekli().fotograf_cek(yol=yol)

    async def kare_al(self) -> Kare:
        """Tek video karesi (dry_run dostu)."""
        self._calisiyor_mi()
        akis = self._akis_gerekli()
        return await akis.kare_al()

    async def video_akisi(
        self,
        *,
        max_kare: Optional[int] = None,
        olay_kare: bool = False,
    ) -> AsyncIterator[Kare]:
        """FPS'li async kare üreteci."""
        self._calisiyor_mi()
        akis = self._akis_gerekli()
        async for kare in akis.akis(max_kare=max_kare, olay_kare=olay_kare):
            yield kare

    # ------------------------------------------------------------------ OCR facade

    def ocr_oku(
        self,
        girdi: GirdiTuru,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
        sahte_metin: Optional[str] = None,
    ) -> OcrSonucu:
        self._calisiyor_mi()
        return self._ocr_gerekli().oku(
            girdi, dil=dil, on_isle=on_isle, sahte_metin=sahte_metin
        )

    def ekran_ocr_oku(
        self,
        bolge: BolgeTuru = None,
        *,
        dil: Optional[str] = None,
        on_isle: Optional[bool] = None,
        sahte_metin: Optional[str] = None,
    ) -> OcrSonucu:
        self._calisiyor_mi()
        if self.ekran is None:
            raise VisionError(
                "Ekran OCR bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.ekran.oku(
            bolge, dil=dil, on_isle=on_isle, sahte_metin=sahte_metin
        )

    def pdf_ocr_oku(
        self,
        yol: PdfGirdi,
        *,
        dil: Optional[str] = None,
        sayfa: Optional[int] = None,
        max_sayfa: Optional[int] = None,
        mod: str = "auto",
        on_isle: Optional[bool] = None,
        sahte_metin: Optional[str] = None,
    ) -> OcrSonucu:
        self._calisiyor_mi()
        if self.pdf is None:
            raise VisionError(
                "PDF OCR bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.pdf.oku(
            yol,
            dil=dil,
            sayfa=sayfa,
            max_sayfa=max_sayfa,
            mod=mod,
            on_isle=on_isle,
            sahte_metin=sahte_metin,
        )

    # ------------------------------------------------------------------ analiz facade

    def nesne_algila(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        etiket_filtre: Optional[Sequence[str]] = None,
        sahte_nesneler: Optional[Sequence[Any]] = None,
    ) -> AnalizSonucu:
        self._calisiyor_mi()
        if self.nesne is None:
            raise VisionError(
                "Nesne algilayici bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        kwargs: dict[str, Any] = {}
        if min_guven is not None:
            kwargs["min_guven"] = min_guven
        if etiket_filtre is not None:
            kwargs["etiket_filtre"] = etiket_filtre
        if sahte_nesneler is not None:
            kwargs["sahte_nesneler"] = sahte_nesneler
        return self.nesne.algila(girdi, **kwargs)

    def sahne_analiz(
        self,
        girdi: GirdiTuru,
        *,
        sahte_sahne: Optional[str] = None,
        etiketler: Optional[Sequence[str]] = None,
    ) -> AnalizSonucu:
        self._calisiyor_mi()
        if self.sahne is None:
            raise VisionError(
                "Sahne analizci bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.sahne.analiz(
            girdi, sahte_sahne=sahte_sahne, etiketler=etiketler
        )

    def renk_analiz(self, girdi: GirdiTuru, **kwargs: Any) -> AnalizSonucu:
        self._calisiyor_mi()
        if self.renk is None:
            raise VisionError(
                "Renk analizci bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.renk.analiz(girdi, **kwargs)

    def qr_analiz(
        self,
        girdi: GirdiTuru,
        *,
        sahte_qr: Optional[Sequence[str]] = None,
        sahte_barkod: Optional[Sequence[str]] = None,
        barkod_oku: Optional[bool] = None,
    ) -> AnalizSonucu:
        self._calisiyor_mi()
        if self.qr is None:
            raise VisionError(
                "QR analizci bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.qr.analiz(
            girdi,
            sahte_qr=sahte_qr,
            sahte_barkod=sahte_barkod,
            barkod_oku=barkod_oku,
        )

    # ------------------------------------------------------------------ yüz facade

    def yuz_algila(
        self,
        girdi: GirdiTuru,
        *,
        min_guven: Optional[float] = None,
        sahte_yuzler: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
    ) -> YuzAlgilamaSonucu:
        self._calisiyor_mi()
        if self.algilama is None:
            raise VisionError(
                "Yuz algilayici bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.algilama.algila(
            girdi,
            min_guven=min_guven,
            sahte_yuzler=sahte_yuzler,
            izin_zorla=izin_zorla,
        )

    def yuz_kaydet(
        self,
        gorunen_ad: str,
        *,
        embedding: Optional[Sequence[float]] = None,
        sablon: Optional[bytes] = None,
        sablon_yolu: Optional[Union[str, Path]] = None,
        kullanici_id: Optional[str] = None,
        izin_zorla: bool = True,
    ) -> KayitliKullanici:
        """Yerel yüz kaydı — buluta gitmez."""
        self._calisiyor_mi()
        if self.kayit is None:
            raise VisionError(
                "Yuz kayit yoneticisi bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.kayit.kaydet(
            gorunen_ad,
            embedding=embedding,
            sablon=sablon,
            sablon_yolu=sablon_yolu,
            kullanici_id=kullanici_id,
            izin_zorla=izin_zorla,
        )

    def yuz_tanima(
        self,
        girdi: Optional[GirdiTuru] = None,
        *,
        embedding: Optional[Sequence[float]] = None,
        min_guven: Optional[float] = None,
        sahte_ad: Optional[str] = None,
        kutular: Optional[Sequence[YuzKutusu]] = None,
        izin_zorla: bool = True,
        algila: bool = True,
    ) -> YuzTanimaSonucu:
        """Yüz tanıma — toggle kapalıysa VisionError; wire'da şablon yok."""
        self._calisiyor_mi()
        if self.tanima is None:
            raise VisionError(
                "Yuz taniyici bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.tanima.tanima(
            girdi,
            embedding=embedding,
            min_guven=min_guven,
            sahte_ad=sahte_ad,
            kutular=kutular,
            izin_zorla=izin_zorla,
            algila=algila,
        )

    def yuz_wire(self, sonuc: YuzTanimaSonucu) -> dict[str, Any]:
        """Tanıma sonucunu wire-güvenli dict'e çevirir (embedding yok)."""
        g = self._gizlilik_gerekli()
        return g.tanima_wire(sonuc)

    # ------------------------------------------------------------------ Vision AI facade

    def gorsel_acikla(
        self,
        girdi: GirdiTuru,
        *,
        sahte_aciklama: Optional[str] = None,
        etiketler: Optional[Sequence[str]] = None,
        dil: str = "tr",
    ) -> VisionAiSonucu:
        self._calisiyor_mi()
        if self.aciklama is None:
            raise VisionError(
                "Gorsel aciklama bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.aciklama.acikla(
            girdi,
            sahte_aciklama=sahte_aciklama,
            etiketler=etiketler,
            dil=dil,
        )

    def gorsel_sor(
        self,
        girdi: GirdiTuru,
        soru: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
    ) -> VisionAiSonucu:
        self._calisiyor_mi()
        if self.vqa is None:
            raise VisionError(
                "Gorsel VQA bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.vqa.sor(girdi, soru, sahte_cevap=sahte_cevap, dil=dil)

    def nesne_say(
        self,
        girdi: GirdiTuru,
        *,
        etiket: Optional[str] = None,
        min_guven: Optional[float] = None,
        sahte_sayim: Optional[int] = None,
        dil: str = "tr",
    ) -> VisionAiSonucu:
        self._calisiyor_mi()
        if self.sayma is None:
            raise VisionError(
                "Nesne sayici bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.sayma.say(
            girdi,
            etiket=etiket,
            min_guven=min_guven,
            sahte_sayim=sahte_sayim,
            dil=dil,
        )

    def multimodal_analiz(
        self,
        girdi: GirdiTuru,
        metin: str,
        *,
        sahte_cevap: Optional[str] = None,
        dil: str = "tr",
        sayim_etiket: Optional[str] = None,
    ) -> VisionAiSonucu:
        self._calisiyor_mi()
        if self.multimodal is None:
            raise VisionError(
                "Multimodal analiz bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.multimodal.analiz(
            girdi,
            metin,
            sahte_cevap=sahte_cevap,
            dil=dil,
            sayim_etiket=sayim_etiket,
        )

    # ------------------------------------------------------------------ özet

    def ozet(self) -> dict[str, Any]:
        """Durum özeti (wire İngilizce anahtarlar; yüz şablonu yok)."""

        def _alt(modul: Any) -> dict[str, Any]:
            if modul is None:
                return {"bound": False}
            try:
                if hasattr(modul, "ozet"):
                    data = dict(modul.ozet())
                    data["bound"] = True
                    return data
                return {
                    "bound": True,
                    "engine": getattr(modul, "motor", None),
                    "running": getattr(modul, "calisiyor", None),
                }
            except Exception as exc:  # noqa: BLE001
                return {"bound": True, "error": str(exc)}

        face_enabled = False
        local_only = True
        if self.gizlilik is not None:
            try:
                face_enabled = self.gizlilik.yuz_tanima_aktif_mi()
                local_only = bool(self.gizlilik.yerel_only)
            except Exception:  # noqa: BLE001
                pass

        return {
            "running": self._calisiyor,
            "engine": self._motor,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "fake": self.zorla_sahte,
            "face_enabled": face_enabled,
            "local_only": local_only,
            "cloud_allowed": False,
            "camera": _alt(self.kamera),
            "stream": _alt(self.akis),
            "ocr": _alt(self.ocr),
            "screen_ocr": _alt(self.ekran),
            "pdf_ocr": _alt(self.pdf),
            "object": _alt(self.nesne),
            "scene": _alt(self.sahne),
            "color": _alt(self.renk),
            "qr": _alt(self.qr),
            "privacy": _alt(self.gizlilik),
            "face_detect": _alt(self.algilama),
            "face_registry": _alt(self.kayit),
            "face_recognize": _alt(self.tanima),
            "caption": _alt(self.aciklama),
            "vqa": _alt(self.vqa),
            "count": _alt(self.sayma),
            "multimodal": _alt(self.multimodal),
        }

    # ------------------------------------------------------------------ iç

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        return "live"

    def _calisiyor_mi(self) -> None:
        if not self._calisiyor:
            raise VisionError(
                "Vision Manager calismiyor; once baslat() cagirin",
                kod="VIS_0051",
                modul=self.ad,
            )

    def _kamera_gerekli(self) -> KameraYoneticisi:
        if self.kamera is None:
            raise VisionError(
                "Kamera yoneticisi bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.kamera

    def _akis_gerekli(self) -> VideoAkis:
        if self.akis is None:
            raise VisionError(
                "Video akis bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.akis

    def _ocr_gerekli(self) -> OcrYoneticisi:
        if self.ocr is None:
            raise VisionError(
                "OCR yoneticisi bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.ocr

    def _gizlilik_gerekli(self) -> YuzGizlilikYoneticisi:
        if self.gizlilik is None:
            raise VisionError(
                "Yuz gizlilik yoneticisi bagli degil",
                kod="VIS_0053",
                modul=self.ad,
            )
        return self.gizlilik

    def _yasam_modulleri(self) -> list[tuple[str, Any]]:
        """baslat/durdur sırası (akis ayrı yönetilir)."""
        return [
            ("privacy", self.gizlilik),
            ("camera", self.kamera),
            ("ocr", self.ocr),
            ("screen_ocr", self.ekran),
            ("pdf_ocr", self.pdf),
            ("object", self.nesne),
            ("scene", self.sahne),
            ("color", self.renk),
            ("qr", self.qr),
            ("face_detect", self.algilama),
            ("face_registry", self.kayit),
            ("face_recognize", self.tanima),
            ("caption", self.aciklama),
            ("vqa", self.vqa),
            ("count", self.sayma),
            ("multimodal", self.multimodal),
        ]

    async def _yayin(self, olay: str, veri: dict[str, Any]) -> None:
        if not self.olay_yayinla or self.bus is None:
            return
        try:
            await self.bus.publish(olay, dict(veri), kaynak=self.ad)
        except Exception:  # noqa: BLE001
            log.debug("Vision olay yayinlanamadi: %s", olay)


def vision_yoneticisi_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    olay_yayinla: bool = False,
    yuz_aktif: Optional[bool] = None,
    kamera_izin: Optional[bool] = None,
    yerel_kok: Optional[Union[str, Path]] = None,
    cihaz: int = 0,
    fps: int = 15,
) -> VisionYoneticisi:
    """Test / demo için hazır VisionYoneticisi üretir (henüz başlatılmaz)."""
    return VisionYoneticisi(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        olustur=True,
        olay_yayinla=olay_yayinla,
        yuz_aktif=yuz_aktif,
        kamera_izin=kamera_izin,
        yerel_kok=yerel_kok,
        cihaz=cihaz,
        fps=fps,
    )


__all__ = [
    "OLAY_VISION_BASLADI",
    "OLAY_VISION_DURDU",
    "VisionYoneticisi",
    "vision_yoneticisi_olustur",
]
