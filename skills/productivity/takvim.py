"""
skills/productivity/takvim.py
-----------------------------
Takvim skill'i.

Görev:
- Yerel JSON takvimde etkinlik listele / ekle / sorgula / sil
- Harici takvim yoksa yerel dosya + dry_run / sahte fallback
- Silme için kullanıcı onayı (calendar_delete)
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
_VARSAYILAN_DEPO = _KOK / "data" / "takvim" / "events.json"

_ISLEM_ANAHTARLAR = {
    "listele": ("listele", "liste", "göster", "goster", "bugün", "bugun", "yarın", "yarin"),
    "ekle": ("ekle", "ekle:", "oluştur", "olustur", "kaydet", "add", "yeni etkinlik"),
    "sorgula": ("sorgula", "ara", "bul", "query", "ne var", "etkinlikler"),
    "sil": ("sil", "kaldır", "kaldir", "delete", "remove"),
}

_SAHTE_ETKINLIKLER = (
    {
        "id": "sahte-001",
        "baslik": "WhiteCore demo toplantısı",
        "baslangic": "2026-08-07T10:00:00+00:00",
        "bitis": "2026-08-07T11:00:00+00:00",
        "aciklama": "Sahte takvim etkinliği",
        "konum": "yerel",
    },
    {
        "id": "sahte-002",
        "baslik": "J.A.R.V.I.S. kontrol",
        "baslangic": "2026-08-08T15:30:00+00:00",
        "bitis": "2026-08-08T16:00:00+00:00",
        "aciklama": "Sahte takip etkinliği",
        "konum": "",
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
    """Komuttan takvim işlemini tahmin eder."""
    n = (komut or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    for islem in ("sil", "ekle", "listele", "sorgula"):
        for a in _ISLEM_ANAHTARLAR[islem]:
            if a in n:
                return islem
    if re.search(r"(?i)\btakvim\b", n):
        return "listele"
    return "listele"


def baslik_ayikla(komut: str) -> Optional[str]:
    """'takvim ekle \"Toplantı\" ...' veya ekle: başlık."""
    m = re.search(r'"([^"]+)"|\'([^\']+)\'', komut or "")
    if m:
        return (m.group(1) or m.group(2) or "").strip() or None
    m = re.search(
        r"(?i)(?:ekle|oluştur|olustur|kaydet|yeni\s+etkinlik)\s*[:=]?\s+(.+)$",
        komut or "",
    )
    if m:
        aday = m.group(1).strip()
        aday = re.split(
            r"\s+(?=\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}|\d{1,2}:\d{2}|bugün|bugun|yarın|yarin)",
            aday,
            maxsplit=1,
        )[0].strip(" .,;:")
        if aday and aday.lower() not in {"takvim", "etkinlik"}:
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
    m = re.search(r"(?i)\b(?:id|etkinlik)\s*[:=]?\s*([a-zA-Z0-9\-]+)\b", komut or "")
    if m:
        return m.group(1)
    m = re.search(r'(?i)sil\s+"([^"]+)"|sil\s+\'([^\']+)\'', komut or "")
    if m:
        return m.group(1) or m.group(2)
    return None


def sorgu_metni_ayikla(komut: str) -> Optional[str]:
    m = re.search(
        r"(?i)(?:sorgula|ara|bul|query)\s*[:=]?\s+(.+)$",
        komut or "",
    )
    if not m:
        return None
    aday = m.group(1).strip().strip("\"'")
    aday = re.sub(r"(?i)^(takvim|etkinlik)\s+", "", aday).strip()
    return aday or None


def sahte_etkinlikler(*, neden: str = "zorla_sahte") -> list[dict[str, Any]]:
    """Harici / yerel depo yokken kullanılacak örnek etkinlikler."""
    out: list[dict[str, Any]] = []
    for e in _SAHTE_ETKINLIKLER:
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
        olaylar = ham.get("events") or ham.get("etkinlikler") or []
    elif isinstance(ham, list):
        olaylar = ham
    else:
        return []
    return [dict(x) for x in olaylar if isinstance(x, dict)]


def _depo_kaydet(yol: Path, etkinlikler: list[dict[str, Any]]) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    paket = {
        "version": 1,
        "updated": _utc_iso(),
        "events": etkinlikler,
    }
    yol.write_text(
        json.dumps(paket, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _gun_filtre(etkinlikler: list[dict[str, Any]], gun: date) -> list[dict[str, Any]]:
    sonuc: list[dict[str, Any]] = []
    for e in etkinlikler:
        dt = _parse_iso(str(e.get("baslangic") or ""))
        if dt and dt.date() == gun:
            sonuc.append(e)
    return sonuc


def _metin_filtre(etkinlikler: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    n = (q or "").strip().lower()
    if not n:
        return list(etkinlikler)
    sonuc: list[dict[str, Any]] = []
    for e in etkinlikler:
        alan = " ".join(
            str(e.get(k) or "")
            for k in ("baslik", "aciklama", "konum", "id")
        ).lower()
        if n in alan:
            sonuc.append(e)
    return sonuc


def etkinlik_listele(
    *,
    depo: str | Path | None = None,
    gun: Optional[date] = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Depodaki etkinlikleri listeler (isteğe bağlı gün filtresi)."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()

    if dry_run:
        return {
            "op": "listele",
            "path": str(yol),
            "events": [],
            "count": 0,
            "engine": "dry_run",
            "dry_run": True,
            "day": gun.isoformat() if gun else None,
        }

    if zorla_sahte:
        olaylar = sahte_etkinlikler(neden="zorla_sahte")
        if gun:
            olaylar = _gun_filtre(olaylar, gun)
        return {
            "op": "listele",
            "path": str(yol),
            "events": olaylar,
            "count": len(olaylar),
            "engine": "sahte",
            "dry_run": False,
            "day": gun.isoformat() if gun else None,
        }

    olaylar = _depo_yukle(yol)
    if gun:
        olaylar = _gun_filtre(olaylar, gun)
    return {
        "op": "listele",
        "path": str(yol),
        "events": olaylar,
        "count": len(olaylar),
        "engine": "local_json",
        "dry_run": False,
        "day": gun.isoformat() if gun else None,
    }


def etkinlik_ekle(
    baslik: str,
    *,
    baslangic: Optional[str] = None,
    bitis: Optional[str] = None,
    aciklama: str = "",
    konum: str = "",
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Yeni etkinlik ekler (yerel JSON)."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()
    baslik_temiz = (baslik or "").strip()
    if not baslik_temiz:
        raise ValueError("Etkinlik başlığı gerekli")

    bas = baslangic or _utc_iso()
    if bitis is None:
        dt = _parse_iso(bas) or datetime.now(timezone.utc)
        bitis = _utc_iso(dt + timedelta(hours=1))

    etkinlik = {
        "id": f"evt-{uuid4().hex[:10]}",
        "baslik": baslik_temiz,
        "baslangic": bas,
        "bitis": bitis,
        "aciklama": aciklama or "",
        "konum": konum or "",
        "created": _utc_iso(),
    }

    if dry_run:
        return {
            "op": "ekle",
            "path": str(yol),
            "event": etkinlik,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte:
        etkinlik["engine"] = "sahte"
        etkinlik["reason"] = "zorla_sahte"
        return {
            "op": "ekle",
            "path": str(yol),
            "event": etkinlik,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte",
        }

    olaylar = _depo_yukle(yol)
    olaylar.append(etkinlik)
    _depo_kaydet(yol, olaylar)
    return {
        "op": "ekle",
        "path": str(yol),
        "event": etkinlik,
        "engine": "local_json",
        "dry_run": False,
        "count": len(olaylar),
    }


def etkinlik_sorgula(
    sorgu: str = "",
    *,
    gun: Optional[date] = None,
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Başlık/açıklama veya güne göre etkinlik arar."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()

    if dry_run:
        return {
            "op": "sorgula",
            "path": str(yol),
            "query": sorgu,
            "events": [],
            "count": 0,
            "engine": "dry_run",
            "dry_run": True,
            "day": gun.isoformat() if gun else None,
        }

    if zorla_sahte:
        olaylar = sahte_etkinlikler(neden="zorla_sahte")
    else:
        olaylar = _depo_yukle(yol)

    if gun:
        olaylar = _gun_filtre(olaylar, gun)
    if sorgu:
        olaylar = _metin_filtre(olaylar, sorgu)

    return {
        "op": "sorgula",
        "path": str(yol),
        "query": sorgu,
        "events": olaylar,
        "count": len(olaylar),
        "engine": "sahte" if zorla_sahte else "local_json",
        "dry_run": False,
        "day": gun.isoformat() if gun else None,
    }


def etkinlik_sil(
    etkinlik_id: str,
    *,
    depo: str | Path | None = None,
    dry_run: bool = False,
    zorla_sahte: bool = False,
) -> dict[str, Any]:
    """Kimliğe göre etkinlik siler."""
    yol = Path(depo).expanduser() if depo else varsayilan_depo_yolu()
    eid = (etkinlik_id or "").strip()
    if not eid:
        raise ValueError("Silinecek etkinlik id gerekli")

    if dry_run:
        return {
            "op": "sil",
            "path": str(yol),
            "id": eid,
            "engine": "dry_run",
            "dry_run": True,
        }

    if zorla_sahte:
        return {
            "op": "sil",
            "path": str(yol),
            "id": eid,
            "engine": "sahte",
            "dry_run": False,
            "reason": "zorla_sahte",
            "deleted": True,
        }

    olaylar = _depo_yukle(yol)
    kalan = [e for e in olaylar if str(e.get("id")) != eid]
    if len(kalan) == len(olaylar):
        raise KeyError(f"Etkinlik bulunamadı: {eid}")
    _depo_kaydet(yol, kalan)
    return {
        "op": "sil",
        "path": str(yol),
        "id": eid,
        "engine": "local_json",
        "dry_run": False,
        "deleted": True,
        "count": len(kalan),
    }


def _baslangic_kur(komut: str, kwargs: dict[str, Any]) -> str:
    if kwargs.get("baslangic"):
        return str(kwargs["baslangic"])
    gun = tarih_ayikla(komut) or datetime.now(timezone.utc).date()
    saat = saat_ayikla(komut) or (9, 0)
    dt = datetime(gun.year, gun.month, gun.day, saat[0], saat[1], tzinfo=timezone.utc)
    return _utc_iso(dt)


class TakvimSkill(SkillTabani):
    """Yerel takvim etkinlikleri (listele / ekle / sorgula / sil)."""

    ad = "takvim"
    aciklama = "Yerel takvimde etkinlik listele, ekle, sorgula, sil"
    kategori = "productivity"
    tehlikeli = False  # yalnızca silme alt işlemi onay ister
    tehlike_eylemi = "calendar_delete"
    anahtarlar = (
        "takvim",
        "etkinlik",
        "etkinlikler",
        "calendar",
        "ajanda",
        "randevu",
        "bugün ne var",
        "bugun ne var",
        "yarın ne var",
        "yarin ne var",
    )
    ornekler = (
        "takvim listele",
        'takvim ekle "Toplantı" 2026-08-10 14:00',
        "takvim sorgula toplantı",
        "takvim sil id:evt-abc123",
        "bugün ne var",
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

        if islem == "sil" and not bool(kwargs.get("onaylandi")):
            return YetenekSonucu.onay_gerekli(
                "Takvim etkinliği silme onayı gerekli",
                yetenek=self.ad,
                veri={
                    "action": self.tehlike_eylemi,
                    "id": kwargs.get("id") or id_ayikla(komut),
                },
            )

        try:
            if islem == "listele":
                bil = etkinlik_listele(
                    depo=depo,
                    gun=gun,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Takvim listeleme planlandı (dry_run): {bil.get('path')}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte takvim: {bil.get('count', 0)} etkinlik"
                else:
                    mesaj = f"{bil.get('count', 0)} etkinlik listelendi"
                return self.ok(mesaj, veri=bil)

            if islem == "ekle":
                baslik = kwargs.get("baslik") or baslik_ayikla(komut)
                if not baslik:
                    return self.hata(
                        'Etkinlik başlığı gerekli. Örnek: takvim ekle "Toplantı" 2026-08-10 14:00',
                        veri={"komut": komut},
                    )
                bil = etkinlik_ekle(
                    str(baslik),
                    baslangic=_baslangic_kur(komut, kwargs),
                    bitis=kwargs.get("bitis"),
                    aciklama=str(kwargs.get("aciklama") or ""),
                    konum=str(kwargs.get("konum") or ""),
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Etkinlik ekleme planlandı (dry_run): {baslik}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte etkinlik eklendi: {baslik}"
                else:
                    mesaj = f"Etkinlik eklendi: {baslik}"
                return self.ok(mesaj, veri=bil)

            if islem == "sorgula":
                sorgu = kwargs.get("sorgu")
                if sorgu is None:
                    sorgu = sorgu_metni_ayikla(komut) or ""
                bil = etkinlik_sorgula(
                    str(sorgu),
                    gun=gun,
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = "Takvim sorgusu planlandı (dry_run)"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte sorgu: {bil.get('count', 0)} sonuç"
                else:
                    mesaj = f"{bil.get('count', 0)} etkinlik bulundu"
                return self.ok(mesaj, veri=bil)

            if islem == "sil":
                eid = kwargs.get("id") or id_ayikla(komut)
                if not eid:
                    return self.hata(
                        "Silinecek etkinlik id gerekli. Örnek: takvim sil id:evt-abc",
                        veri={"komut": komut},
                    )
                bil = etkinlik_sil(
                    str(eid),
                    depo=depo,
                    dry_run=dry_run,
                    zorla_sahte=zorla_sahte,
                )
                if bil.get("dry_run"):
                    mesaj = f"Etkinlik silme planlandı (dry_run): {eid}"
                elif bil.get("engine") == "sahte":
                    mesaj = f"Sahte silme: {eid}"
                else:
                    mesaj = f"Etkinlik silindi: {eid}"
                return self.ok(mesaj, veri=bil)

            return self.desteklenmiyor(f"Bilinmeyen takvim işlemi: {islem}")
        except Exception as exc:
            return self.hata(str(exc), veri={"islem": islem, "komut": komut})


takvim_skill = TakvimSkill()
