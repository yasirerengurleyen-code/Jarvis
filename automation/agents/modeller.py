"""
automation/agents/modeller.py
-----------------------------
Akıllı ajan görev / plan veri modelleri.

Görev:
- Çok adımlı görev planını temsil etmek
- Plan adımı durumu, araç türü ve ajan bağlamı
- Wire JSON anahtarları İngilizce (olay / sync stili)
- config.automation.max_plan_steps ile uyumlu sınır yardımcıları

Not: Planlama / yürütme `planlayici.py` ve `yurutucu.py` içinde;
bu modül yalnızca veri modelleri + serileştirme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from core.base import YetenekDurumu, YetenekSonucu
from core.exceptions import WhiteCoreError

AJAN_MODEL_SURUM = 1

# config.automation.max_plan_steps varsayılanı ile uyumlu
VARSAYILAN_MAX_ADIM = 12


class AjanHata(WhiteCoreError):
    """Akıllı ajan / otomasyon model hataları."""

    varsayilan_kod = "AUT_0001"
    varsayilan_modul = "automation"


class PlanAdimDurumu(str, Enum):
    """Tek bir plan adımının durumu."""

    BEKLIYOR = "pending"
    CALISIYOR = "running"
    BASARILI = "succeeded"
    BASARISIZ = "failed"
    ATLANDI = "skipped"
    ONAY_BEKLIYOR = "awaiting_confirmation"
    IPTAL = "cancelled"


class GorevDurumu(str, Enum):
    """Görev planının genel durumu."""

    TASLAK = "draft"
    HAZIR = "ready"
    CALISIYOR = "running"
    BEKLEMEDE = "paused"
    TAMAMLANDI = "completed"
    BASARISIZ = "failed"
    IPTAL = "cancelled"
    ONAY_BEKLIYOR = "awaiting_confirmation"


class AracTuru(str, Enum):
    """Adımın çağıracağı araç kategorisi."""

    SKILL = "skill"
    PLUGIN = "plugin"
    BUILTIN = "builtin"
    AGENT = "agent"


PlanAdimDurumuGirdi = Union[PlanAdimDurumu, str]
GorevDurumuGirdi = Union[GorevDurumu, str]
AracTuruGirdi = Union[AracTuru, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def adim_durumu_coz(deger: PlanAdimDurumuGirdi) -> PlanAdimDurumu:
    """str / Enum → PlanAdimDurumu."""
    if isinstance(deger, PlanAdimDurumu):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "bekliyor": PlanAdimDurumu.BEKLIYOR,
        "calisiyor": PlanAdimDurumu.CALISIYOR,
        "basarili": PlanAdimDurumu.BASARILI,
        "basarisiz": PlanAdimDurumu.BASARISIZ,
        "atlandi": PlanAdimDurumu.ATLANDI,
        "onay_bekliyor": PlanAdimDurumu.ONAY_BEKLIYOR,
        "iptal": PlanAdimDurumu.IPTAL,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return PlanAdimDurumu(metin)
    except ValueError as hata:
        raise AjanHata(
            f"Bilinmeyen plan adim durumu: {deger!r}",
            kod="AUT_0020",
            modul="automation.agents",
        ) from hata


def gorev_durumu_coz(deger: GorevDurumuGirdi) -> GorevDurumu:
    """str / Enum → GorevDurumu."""
    if isinstance(deger, GorevDurumu):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "taslak": GorevDurumu.TASLAK,
        "hazir": GorevDurumu.HAZIR,
        "calisiyor": GorevDurumu.CALISIYOR,
        "beklemede": GorevDurumu.BEKLEMEDE,
        "tamamlandi": GorevDurumu.TAMAMLANDI,
        "basarisiz": GorevDurumu.BASARISIZ,
        "iptal": GorevDurumu.IPTAL,
        "onay_bekliyor": GorevDurumu.ONAY_BEKLIYOR,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return GorevDurumu(metin)
    except ValueError as hata:
        raise AjanHata(
            f"Bilinmeyen gorev durumu: {deger!r}",
            kod="AUT_0021",
            modul="automation.agents",
        ) from hata


def arac_turu_coz(deger: AracTuruGirdi) -> AracTuru:
    """str / Enum → AracTuru."""
    if isinstance(deger, AracTuru):
        return deger
    metin = str(deger).strip().lower()
    esleme = {
        "yetenek": AracTuru.SKILL,
        "eklenti": AracTuru.PLUGIN,
        "yerlesik": AracTuru.BUILTIN,
        "ajan": AracTuru.AGENT,
    }
    if metin in esleme:
        return esleme[metin]
    try:
        return AracTuru(metin)
    except ValueError as hata:
        raise AjanHata(
            f"Bilinmeyen arac turu: {deger!r}",
            kod="AUT_0022",
            modul="automation.agents",
        ) from hata


def max_adim_siniri(deger: Any = None, *, varsayilan: int = VARSAYILAN_MAX_ADIM) -> int:
    """
    max_plan_steps değerini doğrular.

    None / geçersiz → varsayılan; 1..64 aralığına sıkıştırır.
    """
    if deger is None:
        return int(varsayilan)
    try:
        n = int(deger)
    except (TypeError, ValueError) as hata:
        raise AjanHata(
            f"max_plan_steps gecersiz: {deger!r}",
            kod="AUT_0023",
            modul="automation.agents",
        ) from hata
    if n < 1 or n > 64:
        raise AjanHata(
            f"max_plan_steps 1..64 olmali: {n}",
            kod="AUT_0024",
            modul="automation.agents",
        )
    return n


@dataclass
class PlanAdimi:
    """
    Tek bir ajan plan adımı.

    Wire: id, index, title, tool_type, tool_name, command, args,
          status, dangerous, result?, error?, meta?
    """

    baslik: str
    arac_adi: str = ""
    komut: str = ""
    arac_turu: AracTuru = AracTuru.SKILL
    durum: PlanAdimDurumu = PlanAdimDurumu.BEKLIYOR
    adim_id: str = field(default_factory=lambda: str(uuid4()))
    indeks: int = 0
    args: dict[str, Any] = field(default_factory=dict)
    tehlikeli: bool = False
    sonuc: Optional[dict[str, Any]] = None
    hata: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "id": self.adim_id,
            "index": int(self.indeks),
            "title": self.baslik,
            "tool_type": self.arac_turu.value,
            "tool_name": self.arac_adi,
            "command": self.komut,
            "args": dict(self.args),
            "status": self.durum.value,
            "dangerous": bool(self.tehlikeli),
            "meta": dict(self.meta),
        }
        if self.sonuc is not None:
            veri["result"] = dict(self.sonuc)
        if self.hata is not None:
            veri["error"] = self.hata
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "PlanAdimi":
        if not isinstance(veri, dict):
            raise AjanHata(
                "Plan adimi dict olmali",
                kod="AUT_0025",
                modul="automation.agents",
            )
        baslik = str(veri.get("title") or veri.get("baslik") or "").strip()
        if not baslik:
            raise AjanHata(
                "Plan adimi basligi gerekli",
                kod="AUT_0026",
                modul="automation.agents",
            )
        sonuc_ham = veri.get("result", veri.get("sonuc"))
        sonuc: Optional[dict[str, Any]]
        if sonuc_ham is None:
            sonuc = None
        elif isinstance(sonuc_ham, dict):
            sonuc = dict(sonuc_ham)
        else:
            raise AjanHata(
                "result dict olmali",
                kod="AUT_0027",
                modul="automation.agents",
            )
        hata_ham = veri.get("error", veri.get("hata"))
        return cls(
            baslik=baslik,
            arac_adi=str(veri.get("tool_name") or veri.get("arac_adi") or ""),
            komut=str(veri.get("command") or veri.get("komut") or ""),
            arac_turu=arac_turu_coz(veri.get("tool_type") or veri.get("arac_turu") or "skill"),
            durum=adim_durumu_coz(veri.get("status") or veri.get("durum") or "pending"),
            adim_id=str(veri.get("id") or veri.get("adim_id") or uuid4()),
            indeks=int(veri.get("index") if veri.get("index") is not None else veri.get("indeks") or 0),
            args=dict(veri.get("args") or {}),
            tehlikeli=bool(veri.get("dangerous", veri.get("tehlikeli", False))),
            sonuc=sonuc,
            hata=None if hata_ham is None else str(hata_ham),
            meta=dict(veri.get("meta") or {}),
        )

    def sonucu_uygula(self, sonuc: YetenekSonucu) -> None:
        """YetenekSonucu ile adım durumunu günceller."""
        self.sonuc = sonuc.to_dict()
        if sonuc.durum == YetenekDurumu.BASARILI:
            self.durum = PlanAdimDurumu.BASARILI
            self.hata = None
        elif sonuc.durum == YetenekDurumu.ONAY_BEKLIYOR:
            self.durum = PlanAdimDurumu.ONAY_BEKLIYOR
            self.hata = None
        elif sonuc.durum == YetenekDurumu.IPTAL:
            self.durum = PlanAdimDurumu.IPTAL
            self.hata = sonuc.mesaj or "iptal"
        else:
            self.durum = PlanAdimDurumu.BASARISIZ
            self.hata = sonuc.mesaj or "basarisiz"

    @property
    def tamamlandi_mi(self) -> bool:
        return self.durum in {
            PlanAdimDurumu.BASARILI,
            PlanAdimDurumu.ATLANDI,
            PlanAdimDurumu.IPTAL,
        }

    @property
    def basarili_mi(self) -> bool:
        return self.durum == PlanAdimDurumu.BASARILI


@dataclass
class AjanBaglam:
    """
    Plan oluşturma / yürütme bağlamı.

    Wire: user_id?, project_root?, dry_run, confirm_multi_step, max_steps, extra?
    """

    kullanici_id: Optional[str] = None
    proje_kok: Optional[str] = None
    dry_run: bool = True
    onay_coklu: bool = True
    max_adim: int = VARSAYILAN_MAX_ADIM
    ekstra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.kullanici_id,
            "project_root": self.proje_kok,
            "dry_run": bool(self.dry_run),
            "confirm_multi_step": bool(self.onay_coklu),
            "max_steps": int(self.max_adim),
            "extra": dict(self.ekstra),
        }

    @classmethod
    def from_dict(cls, veri: Optional[dict[str, Any]]) -> "AjanBaglam":
        if veri is None:
            return cls()
        if not isinstance(veri, dict):
            raise AjanHata(
                "Ajan baglami dict olmali",
                kod="AUT_0028",
                modul="automation.agents",
            )
        return cls(
            kullanici_id=(
                None
                if veri.get("user_id", veri.get("kullanici_id")) is None
                else str(veri.get("user_id", veri.get("kullanici_id")))
            ),
            proje_kok=(
                None
                if veri.get("project_root", veri.get("proje_kok")) is None
                else str(veri.get("project_root", veri.get("proje_kok")))
            ),
            dry_run=bool(veri.get("dry_run", True)),
            onay_coklu=bool(
                veri.get("confirm_multi_step", veri.get("onay_coklu", True))
            ),
            max_adim=max_adim_siniri(
                veri.get("max_steps", veri.get("max_adim")),
                varsayilan=VARSAYILAN_MAX_ADIM,
            ),
            ekstra=dict(veri.get("extra") or veri.get("ekstra") or {}),
        )


@dataclass
class GorevPlani:
    """
    Çok adımlı ajan görev planı.

    Wire: v, id, goal, status, steps, context?, created_at, updated_at, meta?
    """

    hedef: str
    adimlar: list[PlanAdimi] = field(default_factory=list)
    durum: GorevDurumu = GorevDurumu.TASLAK
    plan_id: str = field(default_factory=lambda: str(uuid4()))
    baglam: AjanBaglam = field(default_factory=AjanBaglam)
    olusturulma: str = field(default_factory=_utc_iso)
    guncelleme: str = field(default_factory=_utc_iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def dokun(self) -> None:
        """Güncelleme zamanını yeniler."""
        self.guncelleme = _utc_iso()

    def adim_ekle(self, adim: PlanAdimi) -> PlanAdimi:
        """Adım ekler; max_steps aşılırsa hata."""
        sinir = max_adim_siniri(self.baglam.max_adim)
        if len(self.adimlar) >= sinir:
            raise AjanHata(
                f"Plan adim siniri asildi (max={sinir})",
                kod="AUT_0029",
                modul="automation.agents",
                detay={"plan_id": self.plan_id, "max_steps": sinir},
            )
        adim.indeks = len(self.adimlar)
        self.adimlar.append(adim)
        self.dokun()
        return adim

    def sonraki_bekleyen(self) -> Optional[PlanAdimi]:
        """İlk bekleyen / onay bekleyen adımı döner."""
        for adim in self.adimlar:
            if adim.durum in {
                PlanAdimDurumu.BEKLIYOR,
                PlanAdimDurumu.ONAY_BEKLIYOR,
            }:
                return adim
        return None

    def ozet_yenile(self) -> GorevDurumu:
        """
        Adım durumlarından genel görev durumunu türetir.

        Dönüş: güncellenmiş GorevDurumu.
        """
        if not self.adimlar:
            self.durum = GorevDurumu.TASLAK
            self.dokun()
            return self.durum

        durumlar = {a.durum for a in self.adimlar}
        if PlanAdimDurumu.CALISIYOR in durumlar:
            self.durum = GorevDurumu.CALISIYOR
        elif PlanAdimDurumu.ONAY_BEKLIYOR in durumlar:
            self.durum = GorevDurumu.ONAY_BEKLIYOR
        elif PlanAdimDurumu.BASARISIZ in durumlar:
            self.durum = GorevDurumu.BASARISIZ
        elif PlanAdimDurumu.IPTAL in durumlar and not any(
            a.durum == PlanAdimDurumu.BEKLIYOR for a in self.adimlar
        ):
            self.durum = GorevDurumu.IPTAL
        elif all(
            a.durum in {PlanAdimDurumu.BASARILI, PlanAdimDurumu.ATLANDI}
            for a in self.adimlar
        ):
            self.durum = GorevDurumu.TAMAMLANDI
        elif any(a.durum == PlanAdimDurumu.BEKLIYOR for a in self.adimlar):
            # En az bir tamamlanmış / çalışan yoksa hazır
            if any(
                a.durum
                in {
                    PlanAdimDurumu.BASARILI,
                    PlanAdimDurumu.ATLANDI,
                    PlanAdimDurumu.BASARISIZ,
                }
                for a in self.adimlar
            ):
                self.durum = GorevDurumu.BEKLEMEDE
            else:
                self.durum = GorevDurumu.HAZIR
        else:
            self.durum = GorevDurumu.HAZIR

        self.dokun()
        return self.durum

    @property
    def adim_sayisi(self) -> int:
        return len(self.adimlar)

    @property
    def tehlikeli_mi(self) -> bool:
        return any(a.tehlikeli for a in self.adimlar)

    @property
    def onay_gerekli_mi(self) -> bool:
        """Çok adımlı onay veya tehlikeli adım varsa True."""
        if self.baglam.onay_coklu and self.adim_sayisi > 1:
            return True
        return self.tehlikeli_mi

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": AJAN_MODEL_SURUM,
            "id": self.plan_id,
            "goal": self.hedef,
            "status": self.durum.value,
            "steps": [a.to_dict() for a in self.adimlar],
            "context": self.baglam.to_dict(),
            "created_at": self.olusturulma,
            "updated_at": self.guncelleme,
            "meta": dict(self.meta),
            "step_count": self.adim_sayisi,
            "dangerous": self.tehlikeli_mi,
            "needs_confirmation": self.onay_gerekli_mi,
        }

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> "GorevPlani":
        if not isinstance(veri, dict):
            raise AjanHata(
                "Gorev plani dict olmali",
                kod="AUT_0030",
                modul="automation.agents",
            )
        hedef = str(veri.get("goal") or veri.get("hedef") or "").strip()
        if not hedef:
            raise AjanHata(
                "Gorev plani hedefi gerekli",
                kod="AUT_0031",
                modul="automation.agents",
            )
        baglam = AjanBaglam.from_dict(veri.get("context") or veri.get("baglam"))
        adimlar_ham = veri.get("steps") or veri.get("adimlar") or []
        if not isinstance(adimlar_ham, list):
            raise AjanHata(
                "steps liste olmali",
                kod="AUT_0032",
                modul="automation.agents",
            )
        adimlar = [PlanAdimi.from_dict(x) for x in adimlar_ham]
        if len(adimlar) > max_adim_siniri(baglam.max_adim):
            raise AjanHata(
                f"Plan adim siniri asildi (max={baglam.max_adim})",
                kod="AUT_0029",
                modul="automation.agents",
            )
        for i, adim in enumerate(adimlar):
            adim.indeks = i
        return cls(
            hedef=hedef,
            adimlar=adimlar,
            durum=gorev_durumu_coz(veri.get("status") or veri.get("durum") or "draft"),
            plan_id=str(veri.get("id") or veri.get("plan_id") or uuid4()),
            baglam=baglam,
            olusturulma=str(veri.get("created_at") or veri.get("olusturulma") or _utc_iso()),
            guncelleme=str(veri.get("updated_at") or veri.get("guncelleme") or _utc_iso()),
            meta=dict(veri.get("meta") or {}),
        )


def plan_adimi_olustur(
    baslik: str,
    *,
    arac_adi: str = "",
    komut: str = "",
    arac_turu: AracTuruGirdi = AracTuru.SKILL,
    tehlikeli: bool = False,
    args: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
) -> PlanAdimi:
    """Yeni plan adımı fabrikası."""
    baslik_temiz = str(baslik or "").strip()
    if not baslik_temiz:
        raise AjanHata(
            "Plan adimi basligi gerekli",
            kod="AUT_0026",
            modul="automation.agents",
        )
    return PlanAdimi(
        baslik=baslik_temiz,
        arac_adi=str(arac_adi or ""),
        komut=str(komut or ""),
        arac_turu=arac_turu_coz(arac_turu),
        tehlikeli=bool(tehlikeli),
        args=dict(args or {}),
        meta=dict(meta or {}),
    )


def gorev_plani_olustur(
    hedef: str,
    *,
    adimlar: Optional[list[PlanAdimi]] = None,
    baglam: Optional[AjanBaglam] = None,
    meta: Optional[dict[str, Any]] = None,
) -> GorevPlani:
    """Yeni görev planı fabrikası; adımları sırayla ekler."""
    hedef_temiz = str(hedef or "").strip()
    if not hedef_temiz:
        raise AjanHata(
            "Gorev plani hedefi gerekli",
            kod="AUT_0031",
            modul="automation.agents",
        )
    plan = GorevPlani(
        hedef=hedef_temiz,
        baglam=baglam or AjanBaglam(),
        meta=dict(meta or {}),
    )
    for adim in adimlar or []:
        plan.adim_ekle(adim)
    if plan.adimlar:
        plan.durum = GorevDurumu.HAZIR
    return plan


__all__ = [
    "AJAN_MODEL_SURUM",
    "VARSAYILAN_MAX_ADIM",
    "AjanHata",
    "PlanAdimDurumu",
    "GorevDurumu",
    "AracTuru",
    "PlanAdimi",
    "AjanBaglam",
    "GorevPlani",
    "adim_durumu_coz",
    "gorev_durumu_coz",
    "arac_turu_coz",
    "max_adim_siniri",
    "plan_adimi_olustur",
    "gorev_plani_olustur",
]
