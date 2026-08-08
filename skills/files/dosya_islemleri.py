"""
skills/files/dosya_islemleri.py
-------------------------------
Dosya ve klasör işlemleri skill'i.

Görev:
- listele / oku / yaz / kopyala / taşı / sil / klasör oluştur
- Silme tehlikeli (onay + config.dangerous_actions: file_delete)
- dry_run ile güvenli test
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Optional

from core.base import YetenekSonucu
from skills.taban import SkillTabani

_ISLEM_ANAHTARLAR = {
    "listele": ("listele", "liste", "ls", "dir", "göster", "goster"),
    "oku": ("oku", "read", "aç oku", "içeriğini"),
    "yaz": ("yaz", "write", "kaydet", "oluştur dosya", "olustur dosya"),
    "kopyala": ("kopyala", "copy", "kopya"),
    "tasi": ("taşı", "tasi", "move", "hemen taşı"),
    "sil": ("sil", "delete", "kaldır", "kaldir", "remove"),
    "klasor": ("klasör oluştur", "klasor olustur", "mkdir", "klasör aç"),
}


def islem_ayikla(komut: str) -> str:
    """Komuttan işlem türünü tahmin eder."""
    n = (komut or "").strip().lower()
    # Önce açık fiiller (path içinde 'dir' vb. geçmesin diye öncelik)
    for islem in ("sil", "kopyala", "tasi", "yaz", "oku", "klasor", "listele"):
        for a in _ISLEM_ANAHTARLAR[islem]:
            if a in n:
                return islem
    return "listele"

def yollari_ayikla(komut: str) -> list[str]:
    """Tırnaklı veya boşluksuz path benzeri parçaları toplar."""
    yollar = re.findall(r'"([^"]+)"|\'([^\']+)\'', komut or "")
    duz = [a or b for a, b in yollar]
    if duz:
        return duz
    # 'dosya oku C:\temp\a.txt' — son token path gibi mi?
    parcalar = (komut or "").split()
    adaylar = []
    for p in parcalar:
        if any(x in p for x in ("/", "\\", ".", ":")) and p.lower() not in {
            "oku",
            "yaz",
            "sil",
            "dir",
        }:
            adaylar.append(p.strip(".,;"))
    return adaylar


def _yol(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()


def dosya_listele(dizin: str | Path, *, glob_deseni: str = "*") -> list[str]:
    d = _yol(dizin)
    if not d.exists():
        raise FileNotFoundError(f"Dizin yok: {d}")
    if not d.is_dir():
        raise NotADirectoryError(f"Dizin değil: {d}")
    return sorted(str(x.name) for x in d.glob(glob_deseni))


def dosya_oku(yol: str | Path, *, max_bayt: int = 100_000) -> str:
    p = _yol(yol)
    if not p.is_file():
        raise FileNotFoundError(f"Dosya yok: {p}")
    data = p.read_bytes()[:max_bayt]
    return data.decode("utf-8", errors="replace")


def dosya_yaz(
    yol: str | Path,
    icerik: str,
    *,
    dry_run: bool = False,
    üzerine: bool = True,
) -> dict[str, Any]:
    p = _yol(yol)
    if dry_run:
        return {"path": str(p), "dry_run": True, "bytes": len(icerik.encode("utf-8"))}
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not üzerine:
        raise FileExistsError(f"Dosya var: {p}")
    p.write_text(icerik, encoding="utf-8")
    return {"path": str(p), "dry_run": False, "bytes": p.stat().st_size}


def dosya_kopyala(
    kaynak: str | Path,
    hedef: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    k, h = _yol(kaynak), _yol(hedef)
    if dry_run:
        return {"src": str(k), "dst": str(h), "dry_run": True}
    if not k.exists():
        raise FileNotFoundError(f"Kaynak yok: {k}")
    h.parent.mkdir(parents=True, exist_ok=True)
    if k.is_dir():
        shutil.copytree(k, h, dirs_exist_ok=True)
    else:
        shutil.copy2(k, h)
    return {"src": str(k), "dst": str(h), "dry_run": False}


def dosya_tasi(
    kaynak: str | Path,
    hedef: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    k, h = _yol(kaynak), _yol(hedef)
    if dry_run:
        return {"src": str(k), "dst": str(h), "dry_run": True, "op": "move"}
    if not k.exists():
        raise FileNotFoundError(f"Kaynak yok: {k}")
    h.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(k), str(h))
    return {"src": str(k), "dst": str(h), "dry_run": False, "op": "move"}


def dosya_sil(yol: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    p = _yol(yol)
    if dry_run:
        return {"path": str(p), "dry_run": True, "op": "delete"}
    if not p.exists():
        raise FileNotFoundError(f"Yol yok: {p}")
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return {"path": str(p), "dry_run": False, "op": "delete"}


def klasor_olustur(yol: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    p = _yol(yol)
    if dry_run:
        return {"path": str(p), "dry_run": True, "op": "mkdir"}
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p), "dry_run": False, "op": "mkdir"}


class DosyaIslemleriSkill(SkillTabani):
    """Dosya / klasör CRUD işlemleri."""

    ad = "dosya_islemleri"
    aciklama = "Dosya listele, oku, yaz, kopyala, taşı, sil"
    kategori = "files"
    tehlikeli = False  # yalnızca silme alt işlemi onay ister
    tehlike_eylemi = "file_delete"
    anahtarlar = (
        "dosya",
        "listele",
        "dosya oku",
        "dosya yaz",
        "kopyala",
        "taşı",
        "tasi",
        "sil",
        "klasör",
        "klasor",
        "mkdir",
    )
    ornekler = (
        'dosya listele "."',
        'dosya oku "notlar.txt"',
        'dosya sil "temp.txt"',
    )

    async def calistir(self, komut: str, **kwargs: Any):
        islem = str(kwargs.get("islem") or islem_ayikla(komut))
        dry_run = bool(kwargs.get("dry_run", False))
        yollar = list(kwargs.get("yollar") or yollari_ayikla(komut))
        icerik = kwargs.get("icerik")
        if icerik is None:
            m = re.search(r"içerik\s*[=:]\s*(.+)$", komut or "", flags=re.I)
            if m:
                icerik = m.group(1).strip()

        if islem == "sil" and not bool(kwargs.get("onaylandi")):
            return YetenekSonucu.onay_gerekli(
                "Dosya silme onayı gerekli",
                yetenek=self.ad,
                veri={"action": self.tehlike_eylemi, "yollar": yollar},
            )

        try:
            if islem == "listele":
                dizin = yollar[0] if yollar else str(Path.cwd())
                isimler = dosya_listele(dizin)
                return self.ok(
                    f"{len(isimler)} öğe",
                    veri={"dir": str(_yol(dizin)), "items": isimler[:500]},
                )

            if islem == "oku":
                if not yollar:
                    return self.hata("Okunacak dosya yolu gerekli")
                metin = dosya_oku(yollar[0])
                return self.ok("Dosya okundu", veri={"path": yollar[0], "text": metin})

            if islem == "yaz":
                if not yollar:
                    return self.hata("Yazılacak dosya yolu gerekli")
                if icerik is None:
                    icerik = ""
                bil = dosya_yaz(yollar[0], str(icerik), dry_run=dry_run)
                return self.ok("Dosya yazıldı", veri=bil)

            if islem == "kopyala":
                if len(yollar) < 2:
                    return self.hata('Kullanım: kopyala "kaynak" "hedef"')
                bil = dosya_kopyala(yollar[0], yollar[1], dry_run=dry_run)
                return self.ok("Kopyalandı", veri=bil)

            if islem == "tasi":
                if len(yollar) < 2:
                    return self.hata('Kullanım: taşı "kaynak" "hedef"')
                bil = dosya_tasi(yollar[0], yollar[1], dry_run=dry_run)
                return self.ok("Taşındı", veri=bil)

            if islem == "sil":
                if not yollar:
                    return self.hata("Silinecek yol gerekli")
                bil = dosya_sil(yollar[0], dry_run=dry_run)
                return self.ok("Silindi", veri=bil)

            if islem == "klasor":
                if not yollar:
                    return self.hata("Klasör yolu gerekli")
                bil = klasor_olustur(yollar[0], dry_run=dry_run)
                return self.ok("Klasör oluşturuldu", veri=bil)

            return self.desteklenmiyor(f"Bilinmeyen dosya işlemi: {islem}")
        except Exception as exc:
            return self.hata(str(exc), veri={"islem": islem, "yollar": yollar})


dosya_islemleri_skill = DosyaIslemleriSkill()
