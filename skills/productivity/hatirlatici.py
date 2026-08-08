"""
skills/productivity/hatirlatici.py
----------------------------------
Hatırlatıcı skill'i.

Görev:
- Yerel JSON depoda hatırlatıcı listele / ekle / sorgula / tamamla / sil
- Harici hatırlatıcı yoksa yerel dosya + dry_run / sahte fallback
- Silme için kullanıcı onayı (reminder_delete)
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from core.base import YetenekSonucu
from skills.taban import SkillTabani

_KOK = Path(__file__).resolve().parents[2]
_VARSAYILAN_DEPO = _KOK / "data" / "hatirlatici" / "reminders.json"

_ISLEM_ANAHTARLAR = {
    "listele": ("listele", "liste", "göster", "goster", "bekleyen", "açık", "acik"),
    "ekle": ("ekle", "ekle:", "oluştur", "olustur", "kaydet", "add", "yeni hatırlatıcı", "yeni hatirlatici"),
    "sorgula": ("sorgula", "ara", "bul", "query"),
    "tamamla": ("tamamla", "tamamlandı", "tamamlandi", "bitir", "complete", "done", "işaretle", "isaretle"),
    "sil": ("sil", "kaldır", "kaldir", "delete", "remove"),
}

_SAHTE_HATIRLATICILAR = (
    {
        "id": "sahte-r001",
        "baslik": "WhiteCore demo hatırlatması",
        "zaman": "2026-08-07T18:00:00+00:00",
        "aciklama": "Sahte hatırlatıcı",
        "tamamlandi": False,
    },
    {
        "id": "sahte-r002",
        "baslik": "J.A.R.V.I.S. kontrol",
        "zaman": "2026-08-08T09:00:00+00:00",
        "aciklama": "Sahte takip hatırlatması",
        "tamamlandi": False,
    },
)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _parse_iso(metin: str) -> Optional[datetime]:
    s = (metin or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def varsayilan_depo_yolu() -> Path:
    return _VARSAYILAN_DEPO


def islem_ayikla(komut: str) -> str:
    """Komuttan hatırlatıcı işlemini tahmin eder."""
    n = (komut or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    for islem in ("sil", "tamamla", "ekle", "listele", "sorgula"):
        for a in _ISLEM_ANAHTARLAR[islem]:
            if a in n:
                return islem
    if re.search(r"(?i)\b(hatırlatıcı|hatirlatici|reminder|hatırlat|hatirlat)\b", n):
        return "listele"
    return "listele"


def baslik_ayikla(komut: str) -> Optional[str]:
    """'hatırlatıcı ekle \"Su iç\" ...' veya ekle: başlık."""
    m = re.search(r'"([^"]+)"|\'([^\']+)\'', komut or "")
    if m:
        return (m.group(1) or m.group(2) or "").strip() or None
    m = re.search(
        r"(?i)(?:ekle|oluştur|olustur|kaydet|yeni\s+hatırlatıcı|yeni\s+hatirlatici)\s*[:=]?\s+(.+)$",
        komut or "",
    )
    if m:
        aday = m.group(1).strip()
        aday = re.split(
            r"\s+(?=\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}|\d{1,2}:\d{2}|bugün|bugun|yarın|yarin)",
            aday,
            maxsplit=1,
        )[0].strip(" .,;:")
        if aday and aday.lower() not in {
            "hatırlatıcı",
            "hatirlatici",
            "reminder",
            "hatırlat",
            "hatirlat",
        }:
            return aday
    return None


def tarih_ayikla(komut: str) -> Optional[date]:
    """Komuttan tek bir gün tarihi (bugün/yarın/ISO/gg.aa.yyyy)."""
    n = (komut or "").strip().lower()
    bugun = datetime.now(timezone.utc).date()
    if re.search(r"(?i)\bbugün\b|\bbugun\b", n):
        return bugun
    if re.search(r"(?i)\byarın\b|\byarin\b", n):
        return bugun + timedelta(days=1)
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", n)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", n)
    if m:
        gun, ay = int(m.group(1)), int(m.group(2))
        yil = int(m.group(3)) if m.group(3) else bugun.year
        if yil < 100:
            yil += 2000
        try:
            return date(yil, ay, gun)
        except ValueError:
            pass
    return None


def saat_ayikla(komut: str) -> Optional[tuple[int, int]]:
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", komut or "")
    if not m:
        return None
    sa, dk = int(m.group(1)), int(m.group(2))
    if 0 <= sa <= 23 and 0 <= dk <= 59:
        return sa, dk
    return None


def id_ayikla(komut: str) -> Optional[str]:
    # Önce açık id: / id= (skill adı 'hatırlatıcı' yanlışlıkla yakalanmasın)
    m = re.search(r"(?i)\bid\s*[:=]\s*([a-zA-Z0-9\-]+)\b", komut or "")
    if m:
        return m.group(1)
    m = re.search(r"(?i)\bid\s+([a-zA-Z0-9\-]+)\b", komut or "")
    if m:
        return m.group(1)
    m = re.search(
        r'(?i)(?:sil|tamamla)\s+"([^"]+)"|(?:sil|tamamla)\s+\'([^\']+)\'',
        komut or "",
    )
    if m:
        return m.group(1) or m.group(2)
    m = re.search(r"\b(rem-[a-zA-Z0-9]+)\b", komut or "")
    if m:
        return m.group(1)
    return None


def sorgu_metni_ayikla(komut: str) -> Optional[str]:
    m = re.search(
        r"(?i)(?:sorgula|ara|bul|query)\s*[:=]?\s+(.+)$",
        komut or "",
    )
    if not m:
        return None
    aday = m.group(1).strip().strip("\"'")
    aday = re.sub(
        r"(?i)^(hatırlatıcı|hatirlatici|reminder|hatırlat|hatirlat)\s+",
        "",
        aday,
    ).strip()
    return aday or None


def sahte_hatirlaticilar(*, neden: str = "zorla_sahte") -> list[dict[str, Any]]:
    """Harici / yerel depo yokken kullanılacak örnek hatırlatıcılar."""
    out: list[dict[str, Any]] = []
    for e in _SAHTE_HATIRLATICILAR:
        kopya = dict(e)
        kopya["engine"] = "sahte"
        kopya["reason"] = neden
        out.append(kopya)
    return out


def _depo_yukle(yol: Path) -> list[dict[str, Any]]:
    if not yol.is_file():
        return []
    try:
        ham = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(ham, dict):
        kayitlar = ham.get("reminders") or ham.get("hatirlaticilar") or []
    elif isinstance(ham, list):
        kayitlar = ham
    else:
        return []
    return [dict(x) for x in kayitlar if isinstance(x, dict)]


def _depo_kaydet(yol: Path, kayitlar: list[dict[str, Any]]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    paket = {
        "version": 1,
        "updated": _utc_iso(),
        "reminders": kayitlar,
    }
    yol.write_text(
        json.dumps(paket, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _gun_filtre(kayitlar: list[dict[str, Any]], gun: date) -> list[dict[str, Any]]:
    sonuc: list[dict[str, Any]] = []
    for e in kayitlar:
        dt = _parse_iso(str(e.get("zaman") or ""))
        if dt and dt.date() == gun:
            sonuc.append(e)
    return sonuc


def _metin_filtre(kayitlar: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    n = (q or "").strip().lower()
    if not n:
        return list(kayitlar)
    sonuc: list[dict[str, Any]] = []
    for e in kayitlar:
        alan = " ".join(
            str(e.get(k) or "")
            for k in ("baslik", "aciklama", "id")
        ).lower()
        if n in alan:
            sonuc.append(e)
    return sonuc


def _bekleyen_filtre(
    kayitlar: list[dict[str, Any]],
    *,
    sadece_bekleyen: bool = False,
) -> list[dict[str, Any]]:
    if not sadece_bekleyen:
        return list(kayitlar)
    return [e for e in kayitlar if not bool(e.get("tamamlandi"))]


def hatirlatici_listele(
    *,
    depo: str | Path | None = None,
    gun: Optional[date] = None,
    sadece_bekleyen: bool = False,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Depodaki hatırlatıcıları listeler (isteğe bağlı gün / bekleyen filtresi)."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()

    if dry_run:
        return {
            "op": "listele",
            "path": str(yol),
            "reminders": [],
            "count": 0,
            "engine": "dry_run",
            "dry_run": True,
            "day": gun.isoformat() if gun else None,
            "pending_only": sadece_bekleyen,
        }

    if zorla_sahte:
        kayitlar = sahte_hatirlaticilar(neden="zorla_sahte")
        if gun:
            kayitlar = _gun_filtre(kayitlar, gun)
        kayitlar = _bekleyen_filtre(kayitlar, sadece_bekleyen=sadece_bekleyen)
        return {
            "op": "listele",
            "path": str(yol),
            "reminders": kayitlar,
            "count": len(kayitlar),
            "engine": "sahte",
            "dry_run": False,
            "day": gun.isoformat() if gun else None,
            "pending_only": sadece_bekleyen,
        }

    kayitlar = _depo_yukle(yol)
    if gun:
        kayitlar = _gun_filtre(kayitlar, gun)
    kayitlar = _bekleyen_filtre(kayitlar, sadece_bekleyen=sadece_bekleyen)
    return {
        "op": "listele",
        "path": str(yol),
        "reminders": kayitlar,
        "count": len(kayitlar),
        "engine": "local_json",
        "dry_run": False,
        "day": gun.isoformat() if gun else None,
        "pending_only": sadece_bekleyen,
    }


def hatirlatici_ekle(
    baslik: str,
    *,
    zaman: Optional[str] = None,
    aciklama: str = "",
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Yeni hatırlatıcı ekler (yerel JSON)."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()
    baslik_temiz = (baslik or "").strip()
    if not baslik_temiz:
        raise ValueError("Hatırlatıcı başlığı gerekli")

    kayit = {
        "id": f"rem-{uuid4().hex[:10]}",
        "baslik": baslik_temiz,
        "zaman": zaman or _utc_iso(),
        "aciklama": aciklama or "",
        "tamamlandi": False,
        "created": _utc_iso(),
    }

    if dry_run:
        return {
            "op": "ekle",
            "path": str(yol),
            "reminder": kayit,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte:
        kayit["engine"] = "sahte"
        kayit["reason"] = "zorla_sahte"
        return {
            "op": "ekle",
            "path": str(yol),
            "reminder": kayit,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte",
        }

    kayitlar = _depo_yukle(yol)
    kayitlar.append(kayit)
    _depo_kaydet(yol, kayitlar)
    return {
        "op": "ekle",
        "path": str(yol),
        "reminder": kayit,
        "engine": "local_json",
        "dry_run": False,
        "count": len(kayitlar),
    }


def hatirlatici_sorgula(
    sorgu: str = "",
    *,
    gun: Optional[date] = None,
    sadece_bekleyen: bool = False,
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Başlık/açıklama veya güne göre hatırlatıcı arar."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()

    if dry_run:
        return {
            "op": "sorgula",
            "path": str(yol),
            "query": sorgu,
            "reminders": [],
            "count": 0,
            "engine": "dry_run",
            "dry_run": True,
            "day": gun.isoformat() if gun else None,
            "pending_only": sadece_bekleyen,
        }

    if zorla_sahte:
        kayitlar = sahte_hatirlaticilar(neden="zorla_sahte")
    else:
        kayitlar = _depo_yukle(yol)

    if gun:
        kayitlar = _gun_filtre(kayitlar, gun)
    if sorgu:
        kayitlar = _metin_filtre(kayitlar, sorgu)
    kayitlar = _bekleyen_filtre(kayitlar, sadece_bekleyen=sadece_bekleyen)

    return {
        "op": "sorgula",
        "path": str(yol),
        "query": sorgu,
        "reminders": kayitlar,
        "count": len(kayitlar),
        "engine": "sahte" if zorla_sahte else "local_json",
        "dry_run": False,
        "day": gun.isoformat() if gun else None,
        "pending_only": sadece_bekleyen,
    }


def hatirlatici_tamamla(
    hatirlatici_id: str,
    *,
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Kimliğe göre hatırlatıcıyı tamamlandı işaretler."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()
    rid = (hatirlatici_id or "").strip()
    if not rid:
        raise ValueError("Tamamlanacak hatırlatıcı id gerekli")

    if dry_run:
        return {
            "op": "tamamla",
            "path": str(yol),
            "id": rid,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte:
        return {
            "op": "tamamla",
            "path": str(yol),
            "id": rid,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte",
            "completed": True,
        }

    kayitlar = _depo_yukle(yol)
    bulundu: Optional[dict[str, Any]] = None
    for e in kayitlar:
        if str(e.get("id")) == rid:
            e["tamamlandi"] = True
            e["completed_at"] = _utc_iso()
            bulundu = e
            break
    if bulundu is None:
        raise KeyError(f"Hatırlatıcı bulunamadı: {rid}")
    _depo_kaydet(yol, kayitlar)
    return {
        "op": "tamamla",
        "path": str(yol),
        "id": rid,
        "reminder": bulundu,
        "engine": "local_json",
        "dry_run": False,
        "completed": True,
        "count": len(kayitlar),
    }


def hatirlatici_sil(
    hatirlatici_id: str,
    *,
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Kimliğe göre hatırlatıcı siler."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()
    rid = (hatirlatici_id or "").strip()
    if not rid:
        raise ValueError("Silinecek hatırlatıcı id gerekli")

    if dry_run:
        return {
            "op": "sil",
            "path": str(yol),
            "id": rid,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte:
        return {
            "op": "sil",
            "path": str(yol),
            "id": rid,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte",
            "deleted": True,
        }

    kayitlar = _depo_yukle(yol)
    kalan = [e for e in kayitlar if str(e.get("id")) != rid]
    if len(kalan) == len(kayitlar):
        raise KeyError(f"Hatırlatıcı bulunamadı: {rid}")
    _depo_kaydet(yol, kalan)
    return {
        "op": "sil",
        "path": str(yol),
        "id": rid,
        "engine": "local_json",
        "dry_run": False,
        "deleted": True,
        "count": len(kalan),
    }


def _zaman_kur(komut: str, kwargs: dict[str, Any]) -> str:
    if kwargs.get("zaman"):
        return str(kwargs["zaman"])
    gun = tarih_ayikla(komut) or datetime.now(timezone.utc).date()
    saat = saat_ayikla(komut) or (9, 0)
    dt = datetime(gun.year, gun.month, gun.day, saat[0], saat[1], tzinfo=timezone.utc)
    return _utc_iso(dt)


class HatirlaticiSkill(SkillTabani):
    """Yerel hatırlatıcılar (listele / ekle / sorgula / tamamla / sil)."""

    ad = "hatirlatici"
    aciklama = "Yerel hatırlatıcı listele, ekle, sorgula, tamamla, sil"
    kategori = "productivity"
    tehlikeli = False  # yalnızca silme alt işlemi onay ister
    tehlike_eylemi = "reminder_delete"
    anahtarlar = (
        "hatırlatıcı",
        "hatirlatici",
        "hatırlat",
        "hatirlat",
        "reminder",
        "reminders",
        "hatırlatmalar",
        "hatirlatmalar",
        "alarm",
        "todo hatırlat",
    )
    ornekler = (
        "hatırlatıcı listele",
        'hatırlatıcı ekle "Su iç" 2026-08-10 14:00',
        "hatırlatıcı sorgula su",
        "hatırlatıcı tamamla id:rem-abc123",
        "hatırlatıcı sil id:rem-abc123",
    )

    async def calistir(self, komut: str, **kwargs: Any):
        islem = str(kwargs.get("islem") or islem_ayikla(komut))
        dry_run = bool(kwargs.get("dry_run", False))
        zorla_sahte = bool(kwargs.get("zorla_sahte", False))
        depo = kwargs.get("depo")
        gun = kwargs.get("gun")
        if isinstance(gun, str):
            try:
                gun = date.fromisoformat(gun)
            except ValueError:
                gun = None
        if gun is None:
            gun = tarih_ayikla(komut)

        n = (komut or "").strip().lower()
        sadece_bekleyen = bool(
            kwargs.get("sadece_bekleyen")
            or re.search(r"(?i)\bbekleyen\b|\baçık\b|\bacik\b", n)
        )

        if islem == "sil" and not bool(kwargs.get("onaylandi")):
            return YetenekSonucu.onay_gerekli(
                "Hatırlatıcı silme onayı gerekli",
                yetenek=self.ad,
                veri={
                    "action": self.tehlike_eylemi,
                    "id": kwargs.get("id") or id_ayikla(komut),
                },
            )

        try:
            if islem == "listele":
                bil = hatirlatici_listele(
                    depo=depo,
                    gun=gun,
                    sadece_bekleyen=sadece_bekleyen,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Hatırlatıcı listeleme planlandı (dry_run): {bil.get('path')}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte hatırlatıcı: {bil.get('count', 0)} kayıt"
                else:
                    mesaj = f"{bil.get('count', 0)} hatırlatıcı listelendi"
                return self.ok(mesaj, veri=bil)

            if islem == "ekle":
                baslik = kwargs.get("baslik") or baslik_ayikla(komut)
                if not baslik:
                    return self.hata(
                        'Hatırlatıcı başlığı gerekli. Örnek: hatırlatıcı ekle "Su iç" 2026-08-10 14:00',
                        veri={"komut": komut},
                    )
                bil = hatirlatici_ekle(
                    str(baslik),
                    zaman=_zaman_kur(komut, kwargs),
                    aciklama=str(kwargs.get("aciklama") or ""),
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Hatırlatıcı ekleme planlandı (dry_run): {baslik}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte hatırlatıcı eklendi: {baslik}"
                else:
                    mesaj = f"Hatırlatıcı eklendi: {baslik}"
                return self.ok(mesaj, veri=bil)

            if islem == "sorgula":
                sorgu = kwargs.get("sorgu")
                if sorgu is None:
                    sorgu = sorgu_metni_ayikla(komut) or ""
                bil = hatirlatici_sorgula(
                    str(sorgu),
                    gun=gun,
                    sadece_bekleyen=sadece_bekleyen,
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = "Hatırlatıcı sorgusu planlandı (dry_run)"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte sorgu: {bil.get('count', 0)} sonuç"
                else:
                    mesaj = f"{bil.get('count', 0)} hatırlatıcı bulundu"
                return self.ok(mesaj, veri=bil)

            if islem == "tamamla":
                rid = kwargs.get("id") or id_ayikla(komut)
                if not rid:
                    return self.hata(
                        "Tamamlanacak hatırlatıcı id gerekli. Örnek: hatırlatıcı tamamla id:rem-abc",
                        veri={"komut": komut},
                    )
                bil = hatirlatici_tamamla(
                    str(rid),
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Hatırlatıcı tamamlama planlandı (dry_run): {rid}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte tamamlama: {rid}"
                else:
                    mesaj = f"Hatırlatıcı tamamlandı: {rid}"
                return self.ok(mesaj, veri=bil)

            if islem == "sil":
                rid = kwargs.get("id") or id_ayikla(komut)
                if not rid:
                    return self.hata(
                        "Silinecek hatırlatıcı id gerekli. Örnek: hatırlatıcı sil id:rem-abc",
                        veri={"komut": komut},
                    )
                bil = hatirlatici_sil(
                    str(rid),
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Hatırlatıcı silme planlandı (dry_run): {rid}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte silme: {rid}"
                else:
                    mesaj = f"Hatırlatıcı silindi: {rid}"
                return self.ok(mesaj, veri=bil)

            return self.desteklenmiyor(f"Bilinmeyen hatırlatıcı işlemi: {islem}")
        except Exception as exc:
            return self.hata(str(exc), veri={"islem": islem, "komut": komut})


hatirlatici_skill = HatirlaticiSkill()
