"""
skills/kayit.py
---------------
Varsayılan skill kaydı / fabrikası.

Görev:
- Tüm Aşama 5 skill örneklerini tek yerden üretmek
- Engine / SkillYoneticisi başlangıcında toplu kayıt sağlamak
"""

from __future__ import annotations

from typing import Optional, Sequence

from config.ayarlar import Ayarlar
from core.events import EventBus
from skills.files.dosya_islemleri import DosyaIslemleriSkill
from skills.files.pdf_okuyucu import PdfOkuyucuSkill
from skills.media.kamera import KameraSkill
from skills.media.ocr import OcrSkill
from skills.media.qr_okuyucu import QrOkuyucuSkill
from skills.productivity.hatirlatici import HatirlaticiSkill
from skills.productivity.takvim import TakvimSkill
from skills.system.program_ac import ProgramAcSkill
from skills.system.terminal import TerminalSkill
from skills.taban import SkillTabani
from skills.web.arama import WebAramaSkill
from skills.web.hava import HavaSkill
from skills.yoneticisi import SkillYoneticisi

# Kayıt sırası: kategori grupları (system → files → web → media → productivity)
_SKILL_SINIFLARI: tuple[type[SkillTabani], ...] = (
    ProgramAcSkill,
    TerminalSkill,
    DosyaIslemleriSkill,
    PdfOkuyucuSkill,
    WebAramaSkill,
    HavaSkill,
    KameraSkill,
    OcrSkill,
    QrOkuyucuSkill,
    TakvimSkill,
    HatirlaticiSkill,
)


def varsayilan_skilller() -> list[SkillTabani]:
    """Taze skill örnekleri (paylaşılan singleton kullanılmaz)."""
    return [sinif() for sinif in _SKILL_SINIFLARI]


def desteklenen_skill_adlari() -> list[str]:
    """Kayıtlı varsayılan skill sınıf adları."""
    return [sinif.ad for sinif in _SKILL_SINIFLARI]


def skill_yoneticisi_olustur(
    *,
    ayar_yonetici: Optional[Ayarlar] = None,
    bus: Optional[EventBus] = None,
    skilller: Optional[Sequence[SkillTabani]] = None,
) -> SkillYoneticisi:
    """
    SkillYoneticisi üretir ve varsayılan (veya verilen) skill'leri kaydeder.
    """
    liste = list(skilller) if skilller is not None else varsayilan_skilller()
    return SkillYoneticisi(
        ayar_yonetici=ayar_yonetici,
        bus=bus,
        skilller=liste,
    )


__all__ = [
    "varsayilan_skilller",
    "desteklenen_skill_adlari",
    "skill_yoneticisi_olustur",
]
