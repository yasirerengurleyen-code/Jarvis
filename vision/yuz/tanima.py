"""
vision/yuz/tanima.py
--------------------
Yüz tanıma + güven skoru + bilinmeyen + Türkçe karşılama (LOCAL ONLY).

Görev:
- Yerel kayıtlı kullanıcılarla eşleştirme (embedding kosinüs benzerliği)
- Güven skoru + eşik (varsayılan modeller.VARSAYILAN_YUZ_ESIK)
- Bilinmeyen yüz → güvenli "tanınmadı" yolu (şablon üretilmez)
- Türkçe karşılama: bilinen / bilinmeyen (modeller yardımcıları)
- YuzGizlilikYoneticisi: toggle kapalıysa tanıma yok / net hata
- YuzAlgilayici + YuzKayitYoneticisi ile köprü
- dry_run / sahte offline yollar
- Bulut / sync / harici API yok

Gizlilik:
- Embedding yalnızca yerel karşılaştırma için; wire'da yok
- Wire: matched + display_name + confidence + greeting
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.base import ModulTabani
from core.events import EventBus, olay_yolu
from core.exceptions import VisionError
from core.logger import audit_yaz, logger_al
from vision.modeller import (
    BILINMEYEN_KULLANICI_MESAJI,
    BILINEN_KARSILAMA_SABLONU,
    VARSAYILAN_YUZ_ESIK,
    KayitliKullanici,
    VisionMotoru,
    YuzGizlilikPolitikasi,
    YuzKutusu,
    YuzTanimaSonucu,
    guven_sinirla,
)
from vision.yuz.algilama import (
    GirdiTuru,
    YuzAlgilayici,
    yuz_algilayici_olustur,
)
from vision.yuz.gizlilik import (
    YuzGizlilikYoneticisi,
    wire_temizle,
    yuz_gizlilik_olustur,
)
from vision.yuz.kayit import YuzKayitYoneticisi, yuz_kayit_olustur

log = logger_al("vision.yuz.tanima")

# EventBus olay adları (wire anahtarları İngilizce stil)
OLAY_YUZ_TANIMA_BASLADI = "vision.face.recognition.started"
OLAY_YUZ_TANIMA_DURDU = "vision.face.recognition.stopped"
OLAY_YUZ_TANINDI = "vision.face.recognition.recognized"
OLAY_YUZ_BILINMEYEN = "vision.face.recognition.unknown"

# embedding_uretici(girdi) → Sequence[float]
EmbeddingUretici = Callable[[Any], Sequence[float]]
# eslestirici(embedding, kullanicilar, esik) → Optional[(KayitliKullanici, guven)]
EslestiriciTuru = Callable[
    [Sequence[float], Sequence[KayitliKullanici], float],
    Optional[tuple[KayitliKullanici, float]],
]


def kosinus_benzerlik(
    a: Sequence[float],
    b: Sequence[float],
) -> float:
    """
    İki vektör arası kosinüs benzerliği → [0, 1] aralığına sıkıştırılır.

    Boyut uyuşmazsa veya sıfır vektörde 0.0 döner.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    ham = dot / (math.sqrt(na) * math.sqrt(nb))
    # -1..1 → 0..1
    return guven_sinirla((ham + 1.0) / 2.0)


def karsilama_metni(*, eslesti: bool, gorunen_ad: Optional[str] = None) -> str:
    """Türkçe karşılama — modeller şablonlarıyla birebir."""
    if eslesti and gorunen_ad:
        return BILINEN_KARSILAMA_SABLONU.format(ad=str(gorunen_ad).strip())
    return BILINMEYEN_KULLANICI_MESAJI


class YuzTaniyici(ModulTabani):
    """
    Yerel yüz tanıma yöneticisi.

    1) Gizlilik: toggle + kamera izni yoksa → VisionError (tanıma yok)
    2) dry_run → bilinmeyen / dry_run sonucu (eşleşme yok)
    3) zorla_sahte → sahte_ad veya enjekte eşleştirici / embedding
    4) embedding (+ kayıtlı profiller) → kosinüs benzerliği
    """

    ad = "vision.yuz.tanima"
    surum = "0.1.0"
    aciklama = "Yüz tanıma — yerel eşleşme, güven, bilinmeyen, Türkçe karşılama"

    def __init__(
        self,
        *,
        ayarlar: Optional[Ayarlar] = None,
        bus: Optional[EventBus] = None,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        min_guven: Optional[float] = None,
        gizlilik: Optional[YuzGizlilikYoneticisi] = None,
        kayit: Optional[YuzKayitYoneticisi] = None,
        algilayici: Optional[YuzAlgilayici] = None,
        embedding_uretici: Optional[EmbeddingUretici] = None,
        eslestirici: Optional[EslestiriciTuru] = None,
        olay_yayinla: bool = True,
    ) -> None:
        super().__init__()
        self.ayarlar = ayarlar or global_ayarlar
        self.bus = bus or olay_yolu
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.olay_yayinla = bool(olay_yayinla)
        self._embedding_uretici = embedding_uretici
        self._eslestirici = eslestirici

        if gizlilik is not None:
            self.gizlilik = gizlilik
        else:
            self.gizlilik = yuz_gizlilik_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                olay_yayinla=False,
                kamera_izin=True if self.dry_run else None,
                yuz_aktif=True if self.dry_run else None,
            )

        if kayit is not None:
            self.kayit = kayit
        else:
            self.kayit = yuz_kayit_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                gizlilik=self.gizlilik,
                olay_yayinla=False,
            )

        if algilayici is not None:
            self.algilayici = algilayici
        else:
            self.algilayici = yuz_algilayici_olustur(
                ayarlar=self.ayarlar,
                bus=self.bus,
                dry_run=self.dry_run,
                zorla_sahte=self.zorla_sahte,
                gizlilik=self.gizlilik,
                olay_yayinla=False,
            )

        self.min_guven = guven_sinirla(
            min_guven if min_guven is not None else self.gizlilik.min_guven,
            varsayilan=VARSAYILAN_YUZ_ESIK,
        )
        self._son_sonuc: Optional[YuzTanimaSonucu] = None
        self._log = logger_al(f"modul.{self.ad}")
        self._motor = self._motor_sec()

    # ------------------------------------------------------------------ özellik

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def son_sonuc(self) -> Optional[YuzTanimaSonucu]:
        return self._son_sonuc

    def ozet(self) -> dict[str, Any]:
        return {
            "name": self.ad,
            "version": self.surum,
            "engine": self._motor,
            "dry_run": bool(self.dry_run) or self._motor == VisionMotoru.DRY_RUN.value,
            "fake": bool(self.zorla_sahte) or self._motor == VisionMotoru.SAHTE.value,
            "min_confidence": float(self.min_guven),
            "local_only": True,
            "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
            "cloud_allowed": False,
            "face_enabled": self.gizlilik.yuz_tanima_aktif_mi(),
            "camera_permission": self.gizlilik.kamera_izni_var_mi(),
            "user_count": self.kayit.say(izin_zorla=False),
            "injected_embedder": self._embedding_uretici is not None,
            "injected_matcher": self._eslestirici is not None,
            "running": bool(self._calisiyor),
            "last": self._son_sonuc.to_dict() if self._son_sonuc else None,
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
        if not self.kayit.calisiyor:
            try:
                await self.kayit.baslat()
            except Exception as hata:  # noqa: BLE001
                self._log.debug("Kayit baslat atlandi: %s", hata)
        if not self.algilayici.calisiyor:
            try:
                await self.algilayici.baslat()
            except Exception as hata:  # noqa: BLE001
                self._log.debug("Algilayici baslat atlandi: %s", hata)
        self._motor = self._motor_sec()
        self._isaret_basladi()
        detay = self._audit_detay({"engine": self._motor})
        self._audit("vision.face.recognition.started", detay)
        self._yayin(OLAY_YUZ_TANIMA_BASLADI, detay)
        self._log.info("Yuz taniyici basladi motor=%s", self._motor)

    async def durdur(self) -> None:
        if not self._calisiyor:
            return
        self._isaret_durdu()
        detay = self._audit_detay({"engine": self._motor})
        self._audit("vision.face.recognition.stopped", detay)
        self._yayin(OLAY_YUZ_TANIMA_DURDU, detay)
        self._log.info("Yuz taniyici durdu")

    # ------------------------------------------------------------------ izin

    def izin_kontrol(self) -> None:
        """
        Tanıma öncesi gizlilik kapısı.

        Toggle kapalı → VIS_0701; kamera izni yok → VIS_0702.
        """
        self.gizlilik.izin_zorla(tanima_gerekli=True)

    def izinli_mi(self) -> bool:
        return self.gizlilik.islem_izinli_mi(tanima_gerekli=True)

    # ------------------------------------------------------------------ API

    def tanima(
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
        """
        Yüz tanır → YuzTanimaSonucu (güven + karşılama).

        izin_zorla=True: yüz tanıma kapalıysa net hata, tanıma yok.
        dry_run → bilinmeyen / dry_run (eşleşme yok).
        embedding veya embedding_uretici ile yerel kosinüs eşleşmesi.
        sahte_ad (zorla_sahte): kayıtlı görünen ada zorla eşle.
        """
        t0 = time.perf_counter()
        if izin_zorla:
            self.izin_kontrol()

        esik = guven_sinirla(
            min_guven if min_guven is not None else self.min_guven,
            varsayilan=self.min_guven,
        )

        # Kutular: verilen → algılama → boş
        yuz_kutulari: list[YuzKutusu] = []
        if kutular is not None:
            yuz_kutulari = [
                YuzKutusu(
                    x=int(k.x),
                    y=int(k.y),
                    w=int(k.w),
                    h=int(k.h),
                    guven=guven_sinirla(k.guven),
                )
                for k in kutular
            ]
        elif algila and girdi is not None and not (
            self.dry_run or self._motor == VisionMotoru.DRY_RUN.value
        ):
            try:
                # Algılama: kamera izni zaten doğrulandı; toggle tanıma için
                alg = self.algilayici.algila(girdi, izin_zorla=False)
                yuz_kutulari = list(alg.kutular)
            except VisionError:
                raise
            except Exception as hata:  # noqa: BLE001
                self._log.debug("Algilama atlandi: %s", hata)

        # dry_run: tanıma yapılmaz
        if self.dry_run or self._motor == VisionMotoru.DRY_RUN.value:
            sonuc = YuzTanimaSonucu(
                eslesti=False,
                guven=0.0,
                esik=esik,
                kutular=yuz_kutulari,
                motor=VisionMotoru.DRY_RUN,
                dry_run=True,
                neden="dry_run",
            )
            return self._sonucla(sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0)

        # Sahte: görünen ad ile zorla eşle (offline test)
        if self.zorla_sahte or self._motor == VisionMotoru.SAHTE.value:
            if sahte_ad:
                kullanici = self.kayit.getir_ad(sahte_ad, izin_zorla=False)
                if kullanici is None:
                    # Kayıtta yoksa sahte bilinen kullanıcı üretme — bilinmeyen yolu
                    sonuc = YuzTanimaSonucu(
                        eslesti=False,
                        guven=0.0,
                        esik=esik,
                        kutular=yuz_kutulari
                        or [YuzKutusu(x=80, y=60, w=120, h=140, guven=0.9)],
                        motor=VisionMotoru.SAHTE,
                        dry_run=False,
                        neden="sahte_unknown",
                    )
                    return self._sonucla(
                        sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0
                    )
                sonuc = YuzTanimaSonucu(
                    eslesti=True,
                    kullanici_id=kullanici.id,
                    gorunen_ad=kullanici.gorunen_ad,
                    guven=0.95,
                    esik=esik,
                    kutular=yuz_kutulari
                    or [YuzKutusu(x=80, y=60, w=120, h=140, guven=0.95)],
                    motor=VisionMotoru.SAHTE,
                    dry_run=False,
                    neden="zorla_sahte",
                )
                return self._sonucla(
                    sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0
                )

        # Embedding üret / al
        emb = [float(x) for x in embedding] if embedding is not None else None
        if emb is None and self._embedding_uretici is not None:
            try:
                ham = self._embedding_uretici(girdi)
                emb = [float(x) for x in ham] if ham is not None else None
            except Exception as hata:  # noqa: BLE001
                raise VisionError(
                    f"Embedding uretilemedi: {hata}",
                    kod="VIS_0731",
                    modul=self.ad,
                    detay={"error": str(hata)},
                ) from hata

        if emb is None:
            # Embedding yok → bilinmeyen (şablon üretme / gönderme yok)
            sonuc = YuzTanimaSonucu(
                eslesti=False,
                guven=0.0,
                esik=esik,
                kutular=yuz_kutulari,
                motor=VisionMotoru.YEREL if not self.zorla_sahte else VisionMotoru.SAHTE,
                dry_run=False,
                neden="no_embedding",
            )
            return self._sonucla(sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0)

        kullanicilar = self.kayit.listele(sadece_aktif=True, wire=False, izin_zorla=False)
        eslesen = self._eslestir(emb, kullanicilar, esik=esik)

        if eslesen is None:
            sonuc = YuzTanimaSonucu(
                eslesti=False,
                guven=self._en_iyi_guven(emb, kullanicilar),
                esik=esik,
                kutular=yuz_kutulari,
                motor=VisionMotoru.YEREL,
                dry_run=False,
                neden="unknown",
            )
            return self._sonucla(sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0)

        kullanici, guven = eslesen
        sonuc = YuzTanimaSonucu(
            eslesti=True,
            kullanici_id=kullanici.id,
            gorunen_ad=kullanici.gorunen_ad,
            guven=guven,
            esik=esik,
            kutular=yuz_kutulari,
            motor=VisionMotoru.YEREL,
            dry_run=False,
            neden="matched",
        )
        return self._sonucla(sonuc, zaman_ms=(time.perf_counter() - t0) * 1000.0)

    def eslestir_embedding(
        self,
        embedding: Sequence[float],
        *,
        min_guven: Optional[float] = None,
        izin_zorla: bool = True,
    ) -> YuzTanimaSonucu:
        """Yalnızca embedding ile yerel eşleştirme (görüntü yok)."""
        return self.tanima(
            None,
            embedding=embedding,
            min_guven=min_guven,
            izin_zorla=izin_zorla,
            algila=False,
        )

    def karsilama(
        self,
        girdi: Optional[GirdiTuru] = None,
        *,
        embedding: Optional[Sequence[float]] = None,
        sahte_ad: Optional[str] = None,
        izin_zorla: bool = True,
    ) -> str:
        """Tanı + Türkçe karşılama metni."""
        return self.tanima(
            girdi,
            embedding=embedding,
            sahte_ad=sahte_ad,
            izin_zorla=izin_zorla,
        ).karsilama

    def buluta_gonder(self, veri: Any = None) -> None:
        """Yüz tanıma verisi asla buluta gitmez."""
        self.gizlilik.bulut_gonderimini_engelle(veri)

    # ------------------------------------------------------------------ iç — eşleştir

    def _eslestir(
        self,
        embedding: Sequence[float],
        kullanicilar: Sequence[KayitliKullanici],
        *,
        esik: float,
    ) -> Optional[tuple[KayitliKullanici, float]]:
        if self._eslestirici is not None:
            try:
                return self._eslestirici(embedding, list(kullanicilar), float(esik))
            except Exception as hata:  # noqa: BLE001
                raise VisionError(
                    f"Eslestirici basarisiz: {hata}",
                    kod="VIS_0732",
                    modul=self.ad,
                    detay={"error": str(hata)},
                ) from hata

        en_iyi: Optional[KayitliKullanici] = None
        en_iyi_guven = -1.0
        for k in kullanicilar:
            if not k.aktif or not k.embedding:
                continue
            g = kosinus_benzerlik(embedding, k.embedding)
            if g > en_iyi_guven:
                en_iyi_guven = g
                en_iyi = k
        if en_iyi is None:
            return None
        if en_iyi_guven < float(esik):
            return None
        return en_iyi, guven_sinirla(en_iyi_guven)

    def _en_iyi_guven(
        self,
        embedding: Sequence[float],
        kullanicilar: Sequence[KayitliKullanici],
    ) -> float:
        """Eşik altı olsa bile en iyi skoru raporla (bilinmeyen yolu)."""
        en = 0.0
        for k in kullanicilar:
            if not k.embedding:
                continue
            en = max(en, kosinus_benzerlik(embedding, k.embedding))
        return guven_sinirla(en)

    def _motor_sec(self) -> str:
        if self.dry_run:
            return VisionMotoru.DRY_RUN.value
        if self.zorla_sahte:
            return VisionMotoru.SAHTE.value
        if self._embedding_uretici is not None or self._eslestirici is not None:
            return VisionMotoru.YEREL.value
        return VisionMotoru.YEREL.value

    # ------------------------------------------------------------------ iç — sonuç / olay

    def _sonucla(
        self,
        sonuc: YuzTanimaSonucu,
        *,
        zaman_ms: float = 0.0,
    ) -> YuzTanimaSonucu:
        self._son_sonuc = sonuc
        self._motor = sonuc.motor.value
        wire = self.gizlilik.tanima_wire(sonuc)
        detay = self._audit_detay(
            {
                "engine": sonuc.motor.value,
                "matched": bool(sonuc.eslesti),
                "user_id": sonuc.kullanici_id,
                "display_name": sonuc.gorunen_ad,
                "confidence": guven_sinirla(sonuc.guven),
                "threshold": guven_sinirla(sonuc.esik, varsayilan=VARSAYILAN_YUZ_ESIK),
                "greeting": sonuc.karsilama,
                "reason": sonuc.neden,
                "dry_run": bool(sonuc.dry_run),
                "elapsed_ms": float(zaman_ms),
                "face_count": len(sonuc.kutular),
            }
        )
        if sonuc.eslesti:
            self._audit("vision.face.recognition.recognized", detay)
            self._yayin(OLAY_YUZ_TANINDI, wire)
        else:
            self._audit("vision.face.recognition.unknown", detay)
            self._yayin(OLAY_YUZ_BILINMEYEN, wire)
        self._log.info(
            "Yuz tanima matched=%s ad=%s guven=%.3f neden=%s",
            sonuc.eslesti,
            sonuc.gorunen_ad,
            sonuc.guven,
            sonuc.neden,
        )
        return sonuc

    def _audit_detay(self, ekstra: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        temel = self.gizlilik.audit_icin(
            {
                "privacy": YuzGizlilikPolitikasi.YEREL_ONLY.value,
                "local_only": True,
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


def yuz_taniyici_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    min_guven: float = VARSAYILAN_YUZ_ESIK,
    ayarlar: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    kayit: Optional[YuzKayitYoneticisi] = None,
    algilayici: Optional[YuzAlgilayici] = None,
    embedding_uretici: Optional[EmbeddingUretici] = None,
    eslestirici: Optional[EslestiriciTuru] = None,
    olay_yayinla: bool = False,
    kamera_izin: Optional[bool] = True,
    yuz_aktif: Optional[bool] = True,
) -> YuzTaniyici:
    """Test / demo için güvenli varsayılanlarla YuzTaniyici üretir."""
    g = gizlilik
    if g is None:
        g = yuz_gizlilik_olustur(
            ayarlar=ayarlar,
            bus=bus,
            dry_run=dry_run,
            olay_yayinla=False,
            kamera_izin=kamera_izin,
            yuz_aktif=yuz_aktif,
        )
    k = kayit
    if k is None:
        k = yuz_kayit_olustur(
            ayarlar=ayarlar,
            bus=bus,
            dry_run=dry_run,
            gizlilik=g,
            olay_yayinla=False,
        )
    a = algilayici
    if a is None:
        a = yuz_algilayici_olustur(
            ayarlar=ayarlar,
            bus=bus,
            dry_run=dry_run,
            zorla_sahte=zorla_sahte,
            gizlilik=g,
            olay_yayinla=False,
        )
    return YuzTaniyici(
        ayarlar=ayarlar,
        bus=bus,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        gizlilik=g,
        kayit=k,
        algilayici=a,
        embedding_uretici=embedding_uretici,
        eslestirici=eslestirici,
        olay_yayinla=olay_yayinla,
    )


def yuz_tanima(
    girdi: Optional[GirdiTuru] = None,
    *,
    embedding: Optional[Sequence[float]] = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
    sahte_ad: Optional[str] = None,
    min_guven: float = VARSAYILAN_YUZ_ESIK,
    kayit: Optional[YuzKayitYoneticisi] = None,
    gizlilik: Optional[YuzGizlilikYoneticisi] = None,
    kamera_izin: bool = True,
    yuz_aktif: bool = True,
) -> YuzTanimaSonucu:
    """Tek çağrılık yüz tanıma yardımcısı."""
    t = yuz_taniyici_olustur(
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        min_guven=min_guven,
        kayit=kayit,
        gizlilik=gizlilik,
        kamera_izin=kamera_izin,
        yuz_aktif=yuz_aktif,
        olay_yayinla=False,
    )
    return t.tanima(
        girdi,
        embedding=embedding,
        sahte_ad=sahte_ad,
        min_guven=min_guven,
    )


__all__ = [
    "OLAY_YUZ_TANIMA_BASLADI",
    "OLAY_YUZ_TANIMA_DURDU",
    "OLAY_YUZ_TANINDI",
    "OLAY_YUZ_BILINMEYEN",
    "EmbeddingUretici",
    "EslestiriciTuru",
    "YuzTaniyici",
    "kosinus_benzerlik",
    "karsilama_metni",
    "yuz_taniyici_olustur",
    "yuz_tanima",
]
