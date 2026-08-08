"""
plugins/guvenlik.py
-------------------
Eklenti güvenlik politikası.

Görev:
- config.plugins allow_list / deny_list uygulama
- security.sandbox_plugins bayrağı + yol sandbox
- Manifest izin (permissions) kontrolü
- Opsiyonel SHA-256 / imza doğrulama
- Tehlikeli eklenti onay köprüsü (require_confirmation)

Not: Keşif / yükleme `yukleyici.py`, yönetici `yoneticisi.py` içinde;
bu modül yalnızca güvenlik kararları üretir.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from core.exceptions import PluginError
from core.logger import logger_al
from plugins.modeller import (
    VARSAYILAN_PLUGIN_DIZINI,
    PluginKaynak,
    PluginManifesto,
    eklenti_adi_dogrula,
)
from skills.taban import tehlikeli_onay_gerekli

log = logger_al("plugins.guvenlik")

# Sandbox açıkken engellenen tehlikeli izinler
TEHLIKELI_IZINLER: frozenset[str] = frozenset(
    {
        "fs.write",
        "fs.delete",
        "system.exec",
        "system.shutdown",
        "terminal",
        "network.raw",
        "process.spawn",
    }
)

# Sandbox açıkken varsayılan güvenli izinler (bilgi amaçlı)
SANDBOX_IZINLER: frozenset[str] = frozenset(
    {
        "fs.read",
        "network.http",
        "ui.notify",
        "ai.chat",
        "event.emit",
        "config.read",
    }
)

ManifestGirdi = Union[PluginManifesto, str, Any]


@dataclass
class GuvenlikKarari:
    """
    Güvenlik kontrol sonucu.

    Wire: allowed, reason?, code?, sandbox, unsigned?, detail
    """

    izinli: bool
    neden: str = ""
    kod: Optional[str] = None
    sandbox: bool = False
    imzasiz: bool = False
    detay: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "allowed": self.izinli,
            "sandbox": bool(self.sandbox),
            "unsigned": bool(self.imzasiz),
            "detail": dict(self.detay),
        }
        if self.neden:
            veri["reason"] = self.neden
        if self.kod:
            veri["code"] = self.kod
        return veri

    def zorunlu(self) -> "GuvenlikKarari":
        """İzin yoksa PluginError fırlatır; aksi halde kendini döner."""
        if not self.izinli:
            raise PluginError(
                self.neden or "Eklenti guvenlik engeli",
                kod=self.kod or "PLG_0040",
                modul="plugins",
                detay=dict(self.detay),
            )
        return self


class PluginGuvenlik:
    """
    Eklenti allow/deny + sandbox + izin + imza denetleyicisi.

    Yönetici / yükleyici bu sınıfı kullanır.
    """

    def __init__(
        self,
        ayar_yonetici: Any = None,
        *,
        plugin_kok: Optional[Union[str, Path]] = None,
        imza_zorunlu: Optional[bool] = None,
    ) -> None:
        self.ayarlar = ayar_yonetici
        self._plugin_kok = Path(plugin_kok) if plugin_kok else None
        # None → sandbox açıkken dosya/paket için hash varsa doğrula, yoksa imzasız kabul
        # True → sandbox + dosya kaynağında sha256 zorunlu
        self._imza_zorunlu = imza_zorunlu

    # --- config okuma ---------------------------------------------------

    def _ayar(self) -> Any:
        if self.ayarlar is not None:
            return self.ayarlar
        try:
            from config.ayarlar import ayarlar as global_ayarlar

            return global_ayarlar
        except Exception:
            return None

    def _al(self, anahtar: str, varsayilan: Any = None) -> Any:
        ayar = self._ayar()
        if ayar is None:
            return varsayilan
        try:
            if not getattr(ayar, "yuklendi", False) and hasattr(ayar, "yukle"):
                ayar.yukle()
            return ayar.al(anahtar, varsayilan)
        except Exception:
            return varsayilan

    def plugins_etkin_mi(self) -> bool:
        """config.plugins.enabled."""
        return bool(self._al("plugins.enabled", True))

    def sandbox_aktif_mi(self) -> bool:
        """config.security.sandbox_plugins."""
        return bool(self._al("security.sandbox_plugins", True))

    def allow_list(self) -> list[str]:
        ham = self._al("plugins.allow_list", []) or []
        if not isinstance(ham, (list, tuple)):
            return []
        sonuc: list[str] = []
        for x in ham:
            try:
                sonuc.append(eklenti_adi_dogrula(str(x)))
            except PluginError:
                continue
        return sonuc

    def deny_list(self) -> list[str]:
        ham = self._al("plugins.deny_list", []) or []
        if not isinstance(ham, (list, tuple)):
            return []
        sonuc: list[str] = []
        for x in ham:
            try:
                sonuc.append(eklenti_adi_dogrula(str(x)))
            except PluginError:
                continue
        return sonuc

    def plugin_dizini(self) -> Path:
        """Eklenti kök dizini (sandbox yol sınırı)."""
        if self._plugin_kok is not None:
            return self._plugin_kok.resolve()
        dizin = str(self._al("plugins.directory", VARSAYILAN_PLUGIN_DIZINI) or VARSAYILAN_PLUGIN_DIZINI)
        yol = Path(dizin)
        if not yol.is_absolute():
            # plugins/guvenlik.py → proje kökü
            proje_kok = Path(__file__).resolve().parent.parent
            yol = proje_kok / yol
        return yol.resolve()

    def imza_zorunlu_mu(self, kaynak: PluginKaynak = PluginKaynak.DOSYA) -> bool:
        """
        İmza / sha256 zorunlu mu?

        Açık ``imza_zorunlu`` verilmişse onu kullanır.
        Örnek / bellek kaynaklarında asla zorunlu değil.
        Varsayılan: soft (hash meta'da varsa doğrula).
        """
        if kaynak in {PluginKaynak.ORNEK, PluginKaynak.BELLEK}:
            return False
        if self._imza_zorunlu is not None:
            return bool(self._imza_zorunlu)
        # Plan: soft kontrol — zorunluluk yalnızca ctor ile açılır
        return False

    # --- allow / deny ---------------------------------------------------

    def listede_izinli_mi(self, ad: str) -> GuvenlikKarari:
        """
        allow_list / deny_list kontrolü.

        - plugins.enabled=False → engel
        - deny_list öncelikli
        - allow_list doluysa yalnızca listedekiler
        - allow_list boşsa (deny hariç) herkes
        """
        try:
            ad_n = eklenti_adi_dogrula(ad)
        except PluginError as hata:
            return GuvenlikKarari(
                izinli=False,
                neden=hata.mesaj,
                kod=hata.kod,
                sandbox=self.sandbox_aktif_mi(),
                detay={"plugin": ad},
            )

        sandbox = self.sandbox_aktif_mi()
        if not self.plugins_etkin_mi():
            return GuvenlikKarari(
                izinli=False,
                neden="Eklenti sistemi kapali (plugins.enabled=false)",
                kod="PLG_0041",
                sandbox=sandbox,
                detay={"plugin": ad_n},
            )

        deny = set(self.deny_list())
        if ad_n in deny:
            return GuvenlikKarari(
                izinli=False,
                neden=f"Eklenti deny_list'te: {ad_n}",
                kod="PLG_0042",
                sandbox=sandbox,
                detay={"plugin": ad_n, "deny_list": sorted(deny)},
            )

        allow = self.allow_list()
        if allow and ad_n not in set(allow):
            return GuvenlikKarari(
                izinli=False,
                neden=f"Eklenti allow_list disinda: {ad_n}",
                kod="PLG_0043",
                sandbox=sandbox,
                detay={"plugin": ad_n, "allow_list": list(allow)},
            )

        return GuvenlikKarari(
            izinli=True,
            neden="allow/deny ok",
            sandbox=sandbox,
            detay={"plugin": ad_n},
        )

    def izinli_mi(self, ad: str) -> bool:
        """allow/deny soft kontrol."""
        return self.listede_izinli_mi(ad).izinli

    # --- izinler (permissions) ------------------------------------------

    def izin_kontrol(
        self,
        manifesto: PluginManifesto,
        *,
        istenen: Optional[Sequence[str]] = None,
    ) -> GuvenlikKarari:
        """
        Manifest izinlerini denetler.

        Sandbox açıkken TEHLIKELI_IZINLER engellenir.
        ``istenen`` verilirse manifesto.izinler içinde olmalı.
        """
        sandbox = self.sandbox_aktif_mi()
        beyan = {str(x).strip().lower() for x in (manifesto.izinler or ()) if str(x).strip()}

        if sandbox:
            tehlikeli = sorted(beyan & TEHLIKELI_IZINLER)
            if tehlikeli:
                return GuvenlikKarari(
                    izinli=False,
                    neden=f"Sandbox: tehlikeli izinler engellendi: {', '.join(tehlikeli)}",
                    kod="PLG_0044",
                    sandbox=True,
                    detay={
                        "plugin": manifesto.ad,
                        "blocked_permissions": tehlikeli,
                    },
                )

        if istenen:
            gereken = {str(x).strip().lower() for x in istenen if str(x).strip()}
            eksik = sorted(gereken - beyan)
            if eksik:
                return GuvenlikKarari(
                    izinli=False,
                    neden=f"Eklenti izinleri yetersiz: {', '.join(eksik)}",
                    kod="PLG_0045",
                    sandbox=sandbox,
                    detay={
                        "plugin": manifesto.ad,
                        "missing": eksik,
                        "declared": sorted(beyan),
                    },
                )

        return GuvenlikKarari(
            izinli=True,
            neden="permissions ok",
            sandbox=sandbox,
            detay={"plugin": manifesto.ad, "permissions": sorted(beyan)},
        )

    def izin_beyan_edildi_mi(self, manifesto: PluginManifesto, izin: str) -> bool:
        """Manifest bu izni beyan etmiş mi?"""
        hedef = (izin or "").strip().lower()
        return hedef in {str(x).strip().lower() for x in (manifesto.izinler or ())}

    # --- yol sandbox ----------------------------------------------------

    def yol_sandbox_ici_mi(self, yol: Union[str, Path, None]) -> bool:
        """Yol eklenti dizini altında mı? (path traversal engeli)."""
        if yol is None:
            return True
        try:
            hedef = Path(yol).resolve()
            kok = self.plugin_dizini()
            hedef.relative_to(kok)
            return True
        except (ValueError, OSError):
            return False

    def yol_kontrol(self, yol: Union[str, Path, None]) -> GuvenlikKarari:
        """Sandbox açıkken yolun kök altında olmasını zorunlu kılar."""
        sandbox = self.sandbox_aktif_mi()
        if yol is None or not sandbox:
            return GuvenlikKarari(
                izinli=True,
                neden="path ok",
                sandbox=sandbox,
                detay={"path": str(yol) if yol else None},
            )
        if self.yol_sandbox_ici_mi(yol):
            return GuvenlikKarari(
                izinli=True,
                neden="path sandbox ok",
                sandbox=True,
                detay={"path": str(Path(yol).resolve()), "root": str(self.plugin_dizini())},
            )
        return GuvenlikKarari(
            izinli=False,
            neden="Eklenti yolu sandbox disinda",
            kod="PLG_0046",
            sandbox=True,
            detay={"path": str(yol), "root": str(self.plugin_dizini())},
        )

    # --- imza / hash ----------------------------------------------------

    @staticmethod
    def dosya_sha256(yol: Union[str, Path]) -> str:
        """Dosya içeriğinin SHA-256 özeti."""
        p = Path(yol)
        h = hashlib.sha256()
        with p.open("rb") as f:
            for parca in iter(lambda: f.read(65536), b""):
                h.update(parca)
        return h.hexdigest()

    @staticmethod
    def _meta_hash(meta: dict[str, Any]) -> Optional[str]:
        for anahtar in ("sha256", "signature", "hash"):
            deger = meta.get(anahtar)
            if deger:
                return str(deger).strip().lower()
        return None

    def imza_kontrol(
        self,
        manifesto: PluginManifesto,
        *,
        yol: Optional[Union[str, Path]] = None,
    ) -> GuvenlikKarari:
        """
        Manifest meta.sha256 / signature ile dosya hash karşılaştırması.

        - Hash yok + zorunlu değil → imzasız kabul (unsigned=True)
        - Hash yok + zorunlu → engel
        - Hash var + dosya yok → engel
        - Hash uyuşmazlığı → engel
        """
        sandbox = self.sandbox_aktif_mi()
        kaynak = manifesto.kaynak if isinstance(manifesto.kaynak, PluginKaynak) else PluginKaynak.DOSYA
        zorunlu = self.imza_zorunlu_mu(kaynak)
        # Örnek / bellek eklentilerinde imza zorunlu değil
        if kaynak in {PluginKaynak.ORNEK, PluginKaynak.BELLEK}:
            zorunlu = False

        beklenen = self._meta_hash(dict(manifesto.meta or {}))
        hedef = yol or manifesto.yol

        if not beklenen:
            if zorunlu:
                return GuvenlikKarari(
                    izinli=False,
                    neden=f"Eklenti imzasi/sha256 zorunlu: {manifesto.ad}",
                    kod="PLG_0047",
                    sandbox=sandbox,
                    imzasiz=True,
                    detay={"plugin": manifesto.ad},
                )
            return GuvenlikKarari(
                izinli=True,
                neden="unsigned accepted",
                sandbox=sandbox,
                imzasiz=True,
                detay={"plugin": manifesto.ad},
            )

        if not hedef or not Path(hedef).is_file():
            return GuvenlikKarari(
                izinli=False,
                neden=f"Imza dogrulama icin dosya bulunamadi: {manifesto.ad}",
                kod="PLG_0048",
                sandbox=sandbox,
                detay={"plugin": manifesto.ad, "path": str(hedef) if hedef else None},
            )

        try:
            hesap = self.dosya_sha256(hedef)
        except OSError as hata:
            return GuvenlikKarari(
                izinli=False,
                neden=f"Dosya okunamadi: {hata}",
                kod="PLG_0048",
                sandbox=sandbox,
                detay={"plugin": manifesto.ad, "path": str(hedef)},
            )

        if not hmac.compare_digest(hesap.lower(), beklenen.lower()):
            return GuvenlikKarari(
                izinli=False,
                neden=f"Eklenti imza/hash uyusmuyor: {manifesto.ad}",
                kod="PLG_0049",
                sandbox=sandbox,
                detay={
                    "plugin": manifesto.ad,
                    "expected": beklenen,
                    "actual": hesap,
                },
            )

        return GuvenlikKarari(
            izinli=True,
            neden="signature ok",
            sandbox=sandbox,
            imzasiz=False,
            detay={"plugin": manifesto.ad, "sha256": hesap},
        )

    # --- tehlikeli onay -------------------------------------------------

    def tehlikeli_onay_gerekir_mi(
        self,
        manifesto: PluginManifesto,
        *,
        eylem: Optional[str] = None,
    ) -> bool:
        """Tehlikeli manifest için kullanıcı onayı gerekir mi?"""
        if not manifesto.tehlikeli:
            return False
        return tehlikeli_onay_gerekli(
            self._ayar(),
            eylem=eylem or manifesto.ad,
        )

    # --- birleşik yükleme kontrolü --------------------------------------

    def _manifest_coz(self, girdi: ManifestGirdi) -> PluginManifesto:
        if isinstance(girdi, PluginManifesto):
            return girdi
        if isinstance(girdi, str):
            return PluginManifesto(ad=girdi)
        # PluginTabani veya manifesto() veren nesne
        if hasattr(girdi, "manifesto") and callable(girdi.manifesto):
            return girdi.manifesto()
        if hasattr(girdi, "ad"):
            return PluginManifesto(
                ad=str(girdi.ad),
                surum=str(getattr(girdi, "surum", "0.1.0")),
                tehlikeli=bool(getattr(girdi, "tehlikeli", False)),
                izinler=tuple(getattr(girdi, "izinler", ()) or ()),
                kaynak=getattr(girdi, "kaynak", PluginKaynak.DOSYA),
                yol=getattr(girdi, "yol", None),
                meta=dict(getattr(girdi, "_meta", None) or getattr(girdi, "meta", {}) or {}),
            )
        raise PluginError(
            "Gecersiz manifesto girdisi",
            kod="PLG_0040",
            modul="plugins",
        )

    def yukleme_kontrol(
        self,
        girdi: ManifestGirdi,
        *,
        yol: Optional[Union[str, Path]] = None,
        istenen_izinler: Optional[Sequence[str]] = None,
        zorunlu: bool = True,
    ) -> GuvenlikKarari:
        """
        Yükleme öncesi tam güvenlik denetimi.

        Sıra: allow/deny → yol sandbox → izinler → imza.
        ``zorunlu=True`` ise ilk engelde PluginError.
        """
        man = self._manifest_coz(girdi)
        hedef = yol or man.yol
        sandbox = self.sandbox_aktif_mi()

        karar = self.listede_izinli_mi(man.ad)
        if not karar.izinli:
            return karar.zorunlu() if zorunlu else karar

        karar = self.yol_kontrol(hedef)
        if not karar.izinli:
            return karar.zorunlu() if zorunlu else karar

        karar = self.izin_kontrol(man, istenen=istenen_izinler)
        if not karar.izinli:
            return karar.zorunlu() if zorunlu else karar

        karar = self.imza_kontrol(man, yol=hedef)
        if not karar.izinli:
            return karar.zorunlu() if zorunlu else karar

        log.debug(
            "Yukleme guvenlik OK: %s (sandbox=%s, unsigned=%s)",
            man.ad,
            sandbox,
            karar.imzasiz,
        )
        return GuvenlikKarari(
            izinli=True,
            neden="yukleme ok",
            sandbox=sandbox,
            imzasiz=karar.imzasiz,
            detay={"plugin": man.ad, "path": str(hedef) if hedef else None},
        )


def guvenlik_olustur(
    ayar_yonetici: Any = None,
    *,
    plugin_kok: Optional[Union[str, Path]] = None,
    imza_zorunlu: Optional[bool] = None,
) -> PluginGuvenlik:
    """Kolay fabrika."""
    return PluginGuvenlik(
        ayar_yonetici,
        plugin_kok=plugin_kok,
        imza_zorunlu=imza_zorunlu,
    )


__all__ = [
    "TEHLIKELI_IZINLER",
    "SANDBOX_IZINLER",
    "GuvenlikKarari",
    "PluginGuvenlik",
    "guvenlik_olustur",
    "tehlikeli_onay_gerekli",
]
