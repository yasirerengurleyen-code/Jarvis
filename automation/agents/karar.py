"""
automation/agents/karar.py
--------------------------
Karar / politika motoru — yürütme sonrası aksiyon seçer.

Görev:
- Plan + adım sonucu üzerinden politika kararı vermek
- continue / retry / abort / ask_user aksiyonları
- max_retry, geçici hata, tehlikeli adım ve onay kapısı kuralları
- Offline birim testlere uygun (ağ / LLM yok)

Not: Orkestrasyon `ajan.py` içinde; bu modül yalnızca karar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from automation.agents.modeller import (
    AjanHata,
    GorevDurumu,
    GorevPlani,
    PlanAdimDurumu,
    PlanAdimi,
)
from core.base import YetenekDurumu, YetenekSonucu
from core.logger import logger_al

log = logger_al("automation.agents.karar")

# Varsayılan yeniden deneme üst sınırı (adım başına)
VARSAYILAN_MAX_RETRY = 2

# Geçici / yeniden denenebilir hata ipuçları (küçük harf)
_GECICI_HATA_IPUCLARI: tuple[str, ...] = (
    "timeout",
    "timed out",
    "zaman asimi",
    "zaman aşımı",
    "temporary",
    "gecici",
    "geçici",
    "busy",
    "mesgul",
    "meşgul",
    "rate limit",
    "too many",
    "connection reset",
    "connection refused",
    "baglanti",
    "bağlantı",
    "unavailable",
    "retry",
    "yeniden dene",
)

# Yeniden denenmemesi gereken kalıcı kod / mesaj ipuçları
_KALICI_HATA_IPUCLARI: tuple[str, ...] = (
    "aut_0039",
    "aut_0040",
    "aut_0041",
    "aut_0042",
    "desteklenmiyor",
    "not supported",
    "permission denied",
    "yetki reddedildi",
    "invalid",
    "gecersiz",
    "geçersiz",
)


class KararAksiyonu(str, Enum):
    """Politika aksiyonu (wire İngilizce)."""

    DEVAM = "continue"
    YENIDEN_DENE = "retry"
    IPTAL = "abort"
    KULLANICIYA_SOR = "ask_user"


KararAksiyonuGirdi = Union[KararAksiyonu, str]


def karar_aksiyonu_coz(deger: KararAksiyonuGirdi) -> KararAksiyonu:
    """str / Enum → KararAksiyonu."""
    if isinstance(deger, KararAksiyonu):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "continue": KararAksiyonu.DEVAM,
        "devam": KararAksiyonu.DEVAM,
        "retry": KararAksiyonu.YENIDEN_DENE,
        "yeniden_dene": KararAksiyonu.YENIDEN_DENE,
        "yeniden dene": KararAksiyonu.YENIDEN_DENE,
        "abort": KararAksiyonu.IPTAL,
        "iptal": KararAksiyonu.IPTAL,
        "cancel": KararAksiyonu.IPTAL,
        "ask_user": KararAksiyonu.KULLANICIYA_SOR,
        "ask-user": KararAksiyonu.KULLANICIYA_SOR,
        "kullaniciya_sor": KararAksiyonu.KULLANICIYA_SOR,
        "kullanıcıya_sor": KararAksiyonu.KULLANICIYA_SOR,
        "confirm": KararAksiyonu.KULLANICIYA_SOR,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return KararAksiyonu(metin)
    except ValueError as hata:
        raise AjanHata(
            f"Bilinmeyen karar aksiyonu: {deger!r}",
            kod="AUT_0043",
            modul="automation.agents",
        ) from hata


def max_retry_siniri(deger: Any = None, *, varsayilan: int = VARSAYILAN_MAX_RETRY) -> int:
    """max_retry değerini doğrular (0..10)."""
    if deger is None:
        return int(varsayilan)
    try:
        n = int(deger)
    except (TypeError, ValueError) as hata:
        raise AjanHata(
            f"max_retry gecersiz: {deger!r}",
            kod="AUT_0044",
            modul="automation.agents",
        ) from hata
    if n < 0 or n > 10:
        raise AjanHata(
            f"max_retry 0..10 olmali: {n}",
            kod="AUT_0044",
            modul="automation.agents",
        )
    return n


def _metin_birlesik(*parcalar: Any) -> str:
    return " ".join(str(p or "") for p in parcalar).strip().lower()


def hata_gecici_mi(mesaj: Optional[str] = None, *, veri: Optional[dict[str, Any]] = None) -> bool:
    """
    Hata mesajı / veri geçici (retry edilebilir) görünüyor mu?

    Kalıcı ipucu varsa False; geçici ipucu varsa True; aksi halde False.
    """
    kod = ""
    if isinstance(veri, dict):
        kod = str(veri.get("code") or veri.get("kod") or "")
    birlesik = _metin_birlesik(mesaj, kod, *(veri.values() if isinstance(veri, dict) else ()))
    if not birlesik:
        return False
    for ipucu in _KALICI_HATA_IPUCLARI:
        if ipucu in birlesik:
            return False
    for ipucu in _GECICI_HATA_IPUCLARI:
        if ipucu in birlesik:
            return True
    return False


def adim_deneme_sayisi(adim: PlanAdimi) -> int:
    """Adım meta.retry_count değerini döner."""
    try:
        return max(0, int(adim.meta.get("retry_count", 0)))
    except (TypeError, ValueError):
        return 0


@dataclass
class KararSonucu:
    """
    Politika karar çıktısı.

    Wire: action, reason, step_id?, step_index?, retry_count, max_retry,
          done, needs_confirmation, meta?
    """

    aksiyon: KararAksiyonu
    neden: str = ""
    adim_id: Optional[str] = None
    adim_indeks: Optional[int] = None
    deneme: int = 0
    max_retry: int = VARSAYILAN_MAX_RETRY
    bitti: bool = False
    onay_gerekli: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.aksiyon.value,
            "reason": self.neden,
            "step_id": self.adim_id,
            "step_index": self.adim_indeks,
            "retry_count": int(self.deneme),
            "max_retry": int(self.max_retry),
            "done": bool(self.bitti),
            "needs_confirmation": bool(self.onay_gerekli),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "KararSonucu":
        if not isinstance(veri, dict):
            raise AjanHata(
                "Karar sonucu dict olmali",
                kod="AUT_0045",
                modul="automation.agents",
            )
        aksiyon_ham = veri.get("action") or veri.get("aksiyon")
        if aksiyon_ham is None:
            raise AjanHata(
                "Karar sonucu action gerekli",
                kod="AUT_0045",
                modul="automation.agents",
            )
        indeks_ham = veri.get("step_index", veri.get("adim_indeks"))
        return cls(
            aksiyon=karar_aksiyonu_coz(aksiyon_ham),
            neden=str(veri.get("reason") or veri.get("neden") or ""),
            adim_id=(
                None
                if veri.get("step_id", veri.get("adim_id")) is None
                else str(veri.get("step_id", veri.get("adim_id")))
            ),
            adim_indeks=None if indeks_ham is None else int(indeks_ham),
            deneme=int(veri.get("retry_count", veri.get("deneme", 0)) or 0),
            max_retry=max_retry_siniri(
                veri.get("max_retry", veri.get("max_deneme")),
                varsayilan=VARSAYILAN_MAX_RETRY,
            ),
            bitti=bool(veri.get("done", veri.get("bitti", False))),
            onay_gerekli=bool(
                veri.get("needs_confirmation", veri.get("onay_gerekli", False))
            ),
            meta=dict(veri.get("meta") or {}),
        )


class KararMotoru:
    """
    GorevPlani için karar / politika motoru.

    Varsayılan: deterministik kurallar; ağ veya LLM gerekmez.
    """

    def __init__(
        self,
        *,
        max_retry: int = VARSAYILAN_MAX_RETRY,
        otomatik_retry: bool = True,
        ayar_yonetici: Any = None,
    ) -> None:
        self.max_retry = max_retry_siniri(max_retry)
        self.otomatik_retry = bool(otomatik_retry)
        self.ayarlar = ayar_yonetici

    def _ayar_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        if self.ayarlar is None:
            return varsayilan
        try:
            if hasattr(self.ayarlar, "al"):
                return self.ayarlar.al(anahtar, varsayilan)
        except Exception:
            return varsayilan
        return varsayilan

    def _max_retry(self, override: Optional[int] = None) -> int:
        if override is not None:
            return max_retry_siniri(override)
        cfg = self._ayar_al("automation.max_retry", None)
        if cfg is not None:
            return max_retry_siniri(cfg)
        return self.max_retry

    def _sonuc_al(
        self,
        adim: Optional[PlanAdimi],
        sonuc: Optional[YetenekSonucu],
    ) -> Optional[YetenekSonucu]:
        if sonuc is not None:
            return sonuc
        if adim is None or not isinstance(adim.sonuc, dict):
            return None
        durum_ham = adim.sonuc.get("status") or adim.sonuc.get("durum")
        if not durum_ham:
            return None
        try:
            durum = YetenekDurumu(str(durum_ham))
        except ValueError:
            return None
        return YetenekSonucu(
            durum=durum,
            mesaj=str(adim.sonuc.get("message") or adim.sonuc.get("mesaj") or adim.hata or ""),
            veri=dict(adim.sonuc.get("data") or adim.sonuc.get("veri") or {}),
            yetenek=adim.arac_adi or None,
        )

    def _hedef_adim(
        self,
        plan: GorevPlani,
        adim: Optional[PlanAdimi],
    ) -> Optional[PlanAdimi]:
        if adim is not None:
            return adim
        # Önce başarısız / onay bekleyen / iptal; yoksa sonraki bekleyen
        for durum in (
            PlanAdimDurumu.ONAY_BEKLIYOR,
            PlanAdimDurumu.BASARISIZ,
            PlanAdimDurumu.IPTAL,
            PlanAdimDurumu.CALISIYOR,
        ):
            for a in plan.adimlar:
                if a.durum is durum:
                    return a
        return plan.sonraki_bekleyen()

    def degerlendir(
        self,
        plan: GorevPlani,
        *,
        adim: Optional[PlanAdimi] = None,
        sonuc: Optional[YetenekSonucu] = None,
        max_retry: Optional[int] = None,
        onaylandi: bool = False,
    ) -> KararSonucu:
        """
        Plan durumuna göre politika kararı üretir.

        Öncelik:
        1) ONAY_BEKLIYOR → ask_user
        2) IPTAL / tamamlandı → abort veya continue(done)
        3) Başarısız adım → retry / abort / ask_user
        4) Bekleyen adım → continue
        """
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0046",
                modul="automation.agents",
            )

        sinir = self._max_retry(max_retry)
        hedef = self._hedef_adim(plan, adim)
        ys = self._sonuc_al(hedef, sonuc)
        deneme = adim_deneme_sayisi(hedef) if hedef is not None else 0

        def _paket(
            aksiyon: KararAksiyonu,
            neden: str,
            *,
            bitti: bool = False,
            onay: bool = False,
            ekstra: Optional[dict[str, Any]] = None,
        ) -> KararSonucu:
            return KararSonucu(
                aksiyon=aksiyon,
                neden=neden,
                adim_id=None if hedef is None else hedef.adim_id,
                adim_indeks=None if hedef is None else int(hedef.indeks),
                deneme=deneme,
                max_retry=sinir,
                bitti=bitti,
                onay_gerekli=onay,
                meta={
                    "plan_id": plan.plan_id,
                    "plan_status": plan.durum.value,
                    "step_status": None if hedef is None else hedef.durum.value,
                    **dict(ekstra or {}),
                },
            )

        # 1) Kullanıcı onayı bekleniyor
        if plan.durum is GorevDurumu.ONAY_BEKLIYOR or (
            hedef is not None and hedef.durum is PlanAdimDurumu.ONAY_BEKLIYOR
        ):
            if onaylandi:
                return _paket(
                    KararAksiyonu.DEVAM,
                    "Kullanici onayi verildi; plan devam edebilir",
                    ekstra={"approved": True},
                )
            return _paket(
                KararAksiyonu.KULLANICIYA_SOR,
                "Plan veya adim kullanici onayi bekliyor",
                onay=True,
            )

        # 2) İptal
        if plan.durum is GorevDurumu.IPTAL or (
            hedef is not None and hedef.durum is PlanAdimDurumu.IPTAL
        ):
            return _paket(
                KararAksiyonu.IPTAL,
                "Plan veya adim iptal edildi",
                bitti=True,
            )

        # 3) Tamamlandı
        if plan.durum is GorevDurumu.TAMAMLANDI or (
            plan.adimlar
            and all(
                a.durum in {PlanAdimDurumu.BASARILI, PlanAdimDurumu.ATLANDI}
                for a in plan.adimlar
            )
        ):
            return _paket(
                KararAksiyonu.DEVAM,
                "Plan tamamlandi",
                bitti=True,
            )

        # 4) Başarısız adım politikası
        basarisiz = hedef is not None and (
            hedef.durum is PlanAdimDurumu.BASARISIZ
            or (ys is not None and ys.durum in {
                YetenekDurumu.BASARISIZ,
                YetenekDurumu.DESTEKLENMIYOR,
            })
        )
        if basarisiz and hedef is not None:
            mesaj = ""
            veri: dict[str, Any] = {}
            if ys is not None:
                mesaj = ys.mesaj
                veri = dict(ys.veri or {})
                if ys.durum is YetenekDurumu.DESTEKLENMIYOR:
                    return _paket(
                        KararAksiyonu.IPTAL,
                        f"Desteklenmeyen arac/adim: {hedef.baslik}",
                        bitti=True,
                        ekstra={"result_status": ys.durum.value},
                    )
            else:
                mesaj = str(hedef.hata or "")
                if isinstance(hedef.sonuc, dict):
                    veri = dict(hedef.sonuc.get("data") or hedef.sonuc.get("veri") or {})

            # Tehlikeli adım + onay yok → kullanıcıya sor (güvenlik)
            if hedef.tehlikeli and not onaylandi and not plan.baglam.dry_run:
                return _paket(
                    KararAksiyonu.KULLANICIYA_SOR,
                    "Tehlikeli adim basarisiz; kullanici onayi / mudahalesi gerekli",
                    onay=True,
                    ekstra={"dangerous": True, "error": mesaj},
                )

            gecici = hata_gecici_mi(mesaj, veri=veri)
            if (
                self.otomatik_retry
                and gecici
                and deneme < sinir
            ):
                return _paket(
                    KararAksiyonu.YENIDEN_DENE,
                    f"Gecici hata; yeniden denenecek ({deneme + 1}/{sinir})",
                    ekstra={"error": mesaj, "transient": True},
                )

            # Kalıcı hata veya retry tükendi → abort
            if deneme >= sinir:
                neden = f"Yeniden deneme siniri asildi ({deneme}/{sinir})"
            elif not gecici:
                neden = f"Kalici hata; iptal: {mesaj or hedef.baslik}"
            else:
                neden = f"Otomatik retry kapali; iptal: {mesaj or hedef.baslik}"
            return _paket(
                KararAksiyonu.IPTAL,
                neden,
                bitti=True,
                ekstra={"error": mesaj, "transient": gecici},
            )

        # 5) Bekleyen / hazır / çalışan → devam
        sonraki = plan.sonraki_bekleyen()
        if sonraki is not None or plan.durum in {
            GorevDurumu.HAZIR,
            GorevDurumu.CALISIYOR,
            GorevDurumu.BEKLEMEDE,
            GorevDurumu.TASLAK,
        }:
            # Çok adımlı / tehlikeli ve onay yok (dry_run değil) → sor
            if (
                not onaylandi
                and not plan.baglam.dry_run
                and plan.onay_gerekli_mi
                and plan.durum in {GorevDurumu.HAZIR, GorevDurumu.TASLAK}
            ):
                return _paket(
                    KararAksiyonu.KULLANICIYA_SOR,
                    "Cok adimli / tehlikeli plan kullanici onayi gerektirir",
                    onay=True,
                )
            return _paket(
                KararAksiyonu.DEVAM,
                "Sonraki adima devam",
                ekstra={
                    "next_step_id": None if sonraki is None else sonraki.adim_id,
                    "next_step_index": None if sonraki is None else sonraki.indeks,
                },
            )

        # 6) Belirsiz başarısız plan durumu
        if plan.durum is GorevDurumu.BASARISIZ:
            return _paket(
                KararAksiyonu.IPTAL,
                "Plan basarisiz durumda",
                bitti=True,
            )

        return _paket(
            KararAksiyonu.DEVAM,
            "Varsayilan devam",
        )

    def uygula(
        self,
        plan: GorevPlani,
        karar: KararSonucu,
        *,
        onaylandi: bool = False,
    ) -> GorevPlani:
        """
        Kararı plana uygular (durum mutasyonu).

        - retry → ilgili adımı BEKLIYOR yapar, retry_count artırır
        - abort → plan/adım IPTAL
        - ask_user → ONAY_BEKLIYOR
        - continue → özet yenile; onaylandıysa onay bayrağını temizle
        """
        if not isinstance(plan, GorevPlani):
            raise AjanHata(
                "GorevPlani bekleniyor",
                kod="AUT_0046",
                modul="automation.agents",
            )
        if not isinstance(karar, KararSonucu):
            raise AjanHata(
                "KararSonucu bekleniyor",
                kod="AUT_0045",
                modul="automation.agents",
            )

        hedef: Optional[PlanAdimi] = None
        if karar.adim_id:
            for a in plan.adimlar:
                if a.adim_id == karar.adim_id:
                    hedef = a
                    break
        if hedef is None and karar.adim_indeks is not None:
            for a in plan.adimlar:
                if a.indeks == karar.adim_indeks:
                    hedef = a
                    break

        if karar.aksiyon is KararAksiyonu.YENIDEN_DENE:
            if hedef is None:
                raise AjanHata(
                    "Retry icin hedef adim gerekli",
                    kod="AUT_0047",
                    modul="automation.agents",
                )
            onceki = adim_deneme_sayisi(hedef)
            hedef.meta["retry_count"] = onceki + 1
            hedef.durum = PlanAdimDurumu.BEKLIYOR
            hedef.hata = None
            hedef.sonuc = None
            if plan.durum in {GorevDurumu.BASARISIZ, GorevDurumu.BEKLEMEDE}:
                plan.durum = GorevDurumu.HAZIR
            plan.meta["decision"] = karar.to_dict()
            plan.dokun()
            log.info(
                "Retry uygulandi: plan=%s step=%s deneme=%s",
                plan.plan_id,
                hedef.indeks,
                hedef.meta["retry_count"],
            )
            return plan

        if karar.aksiyon is KararAksiyonu.IPTAL:
            if hedef is not None and hedef.durum not in {
                PlanAdimDurumu.BASARILI,
                PlanAdimDurumu.ATLANDI,
            }:
                hedef.durum = PlanAdimDurumu.IPTAL
                if not hedef.hata:
                    hedef.hata = karar.neden or "abort"
            # Bekleyenleri iptal
            for a in plan.adimlar:
                if a.durum is PlanAdimDurumu.BEKLIYOR:
                    a.durum = PlanAdimDurumu.IPTAL
                    a.hata = a.hata or "abort"
            plan.durum = GorevDurumu.IPTAL
            plan.meta["decision"] = karar.to_dict()
            plan.dokun()
            log.info("Abort uygulandi: plan=%s", plan.plan_id)
            return plan

        if karar.aksiyon is KararAksiyonu.KULLANICIYA_SOR:
            plan.durum = GorevDurumu.ONAY_BEKLIYOR
            if hedef is not None:
                hedef.durum = PlanAdimDurumu.ONAY_BEKLIYOR
            else:
                sonraki = plan.sonraki_bekleyen()
                if sonraki is not None:
                    sonraki.durum = PlanAdimDurumu.ONAY_BEKLIYOR
            plan.meta["decision"] = karar.to_dict()
            plan.dokun()
            return plan

        # continue
        if onaylandi:
            for a in plan.adimlar:
                if a.durum is PlanAdimDurumu.ONAY_BEKLIYOR:
                    a.durum = PlanAdimDurumu.BEKLIYOR
                    a.hata = None
            if plan.durum is GorevDurumu.ONAY_BEKLIYOR:
                plan.durum = GorevDurumu.HAZIR
        plan.ozet_yenile()
        plan.meta["decision"] = karar.to_dict()
        plan.dokun()
        return plan

    def degerlendir_ve_uygula(
        self,
        plan: GorevPlani,
        *,
        adim: Optional[PlanAdimi] = None,
        sonuc: Optional[YetenekSonucu] = None,
        max_retry: Optional[int] = None,
        onaylandi: bool = False,
    ) -> tuple[GorevPlani, KararSonucu]:
        """degerlendir + uygula birleşik yardımcı."""
        karar = self.degerlendir(
            plan,
            adim=adim,
            sonuc=sonuc,
            max_retry=max_retry,
            onaylandi=onaylandi,
        )
        return self.uygula(plan, karar, onaylandi=onaylandi), karar


def karar_motoru_olustur(
    *,
    max_retry: int = VARSAYILAN_MAX_RETRY,
    otomatik_retry: bool = True,
    ayar_yonetici: Any = None,
) -> KararMotoru:
    """KararMotoru fabrikası."""
    return KararMotoru(
        max_retry=max_retry,
        otomatik_retry=otomatik_retry,
        ayar_yonetici=ayar_yonetici,
    )


__all__ = [
    "VARSAYILAN_MAX_RETRY",
    "KararAksiyonu",
    "KararAksiyonuGirdi",
    "KararSonucu",
    "KararMotoru",
    "karar_aksiyonu_coz",
    "max_retry_siniri",
    "hata_gecici_mi",
    "adim_deneme_sayisi",
    "karar_motoru_olustur",
]
