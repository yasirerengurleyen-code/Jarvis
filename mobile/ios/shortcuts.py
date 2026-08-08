"""
mobile/ios/shortcuts.py
-----------------------
Apple Shortcuts / companion köprü sözleşmesi.

Görev:
- whitecore:// ve shortcuts:// URL scheme üretimi / ayrıştırma
- x-callback-url uyumlu payload oluşturma
- Shortcuts yükü ↔ MobilKomutIstegi dönüşümü
- dry_run / sahte modda gerçek iPhone olmadan test

Not: Native Swift uygulaması sonraki sürüm; bu modül PC host sözleşmesi.
     Gerçek iletim `kopru.py` / Mobile Manager üst katmanda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from uuid import uuid4

from config.ayarlar import Ayarlar, ayarlar as global_ayarlar
from core.exceptions import MobileBridgeError
from core.logger import audit_yaz, logger_al
from mobile.bridge.komutlar import (
    KomutDurum,
    KomutYon,
    MobilKomut,
    MobilKomutIstegi,
    MobilKomutSozlesmesi,
    MobilKomutYaniti,
    komut_coz,
    komut_yonu,
    tehlikeli_mi,
)

log = logger_al("mobile.ios.shortcuts")

SHORTCUTS_SOZLESME_SURUM = 1

# Companion uygulama URL şeması (gelecek native istemci)
VARSAYILAN_SCHEME = "whitecore"
# Apple Shortcuts uygulaması
APPLE_SHORTCUTS_SCHEME = "shortcuts"

# Bilinen kısayol görünen adları (iOS Shortcuts uygulamasında)
VARSAYILAN_KISAYOL_ADLARI: dict[str, str] = {
    "find_phone": "WhiteCore Find Phone",
    "battery_status": "WhiteCore Battery",
    "send_notification": "WhiteCore Notify",
    "open_camera": "WhiteCore Camera",
    "request_location": "WhiteCore Location",
    "shutdown_pc": "WhiteCore Shutdown PC",
    "open_vscode": "WhiteCore Open VS Code",
    "open_chrome": "WhiteCore Open Chrome",
    "send_file": "WhiteCore Send File",
    "take_screenshot": "WhiteCore Screenshot",
}


class ShortcutAksiyon(str, Enum):
    """Shortcuts / companion üzerinden tetiklenebilen aksiyonlar."""

    FIND_PHONE = "find_phone"
    BATTERY_STATUS = "battery_status"
    SEND_NOTIFICATION = "send_notification"
    OPEN_CAMERA = "open_camera"
    REQUEST_LOCATION = "request_location"
    SHUTDOWN_PC = "shutdown_pc"
    OPEN_VSCODE = "open_vscode"
    OPEN_CHROME = "open_chrome"
    SEND_FILE = "send_file"
    TAKE_SCREENSHOT = "take_screenshot"
    # Companion özel: eşleştirme / ping
    PAIR = "pair"
    PING = "ping"


ShortcutAksiyonGirdi = Union[ShortcutAksiyon, MobilKomut, str]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def aksiyon_coz(deger: ShortcutAksiyonGirdi) -> ShortcutAksiyon:
    """str / Enum / MobilKomut → ShortcutAksiyon."""
    if isinstance(deger, ShortcutAksiyon):
        return deger
    if isinstance(deger, MobilKomut):
        metin = deger.value
    else:
        metin = str(deger).strip().lower()
    try:
        return ShortcutAksiyon(metin)
    except ValueError as hata:
        raise MobileBridgeError(
            f"Bilinmeyen shortcut aksiyonu: {deger!r}",
            kod="MOB_0050",
            modul="mobile.ios.shortcuts",
        ) from hata


def kisayol_adi(aksiyon: ShortcutAksiyonGirdi) -> str:
    """Aksiyon için varsayılan Apple Shortcuts görünen adı."""
    a = aksiyon_coz(aksiyon)
    return VARSAYILAN_KISAYOL_ADLARI.get(a.value, f"WhiteCore {a.value}")


def mobil_komuta(aksiyon: ShortcutAksiyonGirdi) -> Optional[MobilKomut]:
    """Shortcut aksiyonunu MobilKomut'a çevirir; pair/ping için None."""
    a = aksiyon_coz(aksiyon)
    if a in {ShortcutAksiyon.PAIR, ShortcutAksiyon.PING}:
        return None
    try:
        return komut_coz(a.value)
    except MobileBridgeError:
        return None


@dataclass
class ShortcutYuk:
    """
    Apple Shortcuts / companion wire yükü.

    Wire JSON anahtarları İngilizce:
      v, action, device_id?, id, ts, args, token?,
      x_success?, x_error?, x_cancel?, source
    """

    aksiyon: ShortcutAksiyon
    args: dict[str, Any] = field(default_factory=dict)
    istek_id: str = field(default_factory=lambda: uuid4().hex)
    zaman: str = field(default_factory=_utc_iso)
    cihaz_id: Optional[str] = None
    token: Optional[str] = None
    x_success: Optional[str] = None
    x_error: Optional[str] = None
    x_cancel: Optional[str] = None
    kaynak: str = "shortcuts"
    surum: int = SHORTCUTS_SOZLESME_SURUM

    def to_dict(self) -> dict[str, Any]:
        veri: dict[str, Any] = {
            "v": int(self.surum),
            "action": self.aksiyon.value,
            "id": self.istek_id,
            "ts": self.zaman,
            "args": dict(self.args),
            "source": self.kaynak,
        }
        if self.cihaz_id:
            veri["device_id"] = self.cihaz_id
        if self.token:
            veri["token"] = self.token
        if self.x_success:
            veri["x_success"] = self.x_success
        if self.x_error:
            veri["x_error"] = self.x_error
        if self.x_cancel:
            veri["x_cancel"] = self.x_cancel
        return veri

    @classmethod
    def from_dict(cls, veri: dict[str, Any]) -> ShortcutYuk:
        if not isinstance(veri, dict):
            raise MobileBridgeError(
                "Shortcut yuk dict olmali",
                kod="MOB_0051",
                modul="mobile.ios.shortcuts",
            )
        aksiyon_ham = veri.get("action") or veri.get("command") or veri.get("aksiyon")
        if not aksiyon_ham:
            raise MobileBridgeError(
                "action zorunlu",
                kod="MOB_0052",
                modul="mobile.ios.shortcuts",
            )
        args = veri.get("args") or {}
        if not isinstance(args, dict):
            raise MobileBridgeError(
                "Shortcut args dict olmali",
                kod="MOB_0053",
                modul="mobile.ios.shortcuts",
            )
        return cls(
            aksiyon=aksiyon_coz(aksiyon_ham),
            args=dict(args),
            istek_id=str(veri.get("id") or uuid4().hex),
            zaman=str(veri.get("ts") or _utc_iso()),
            cihaz_id=veri.get("device_id") or veri.get("cihaz_id"),
            token=veri.get("token"),
            x_success=veri.get("x_success"),
            x_error=veri.get("x_error"),
            x_cancel=veri.get("x_cancel"),
            kaynak=str(veri.get("source") or veri.get("kaynak") or "shortcuts"),
            surum=int(veri.get("v", SHORTCUTS_SOZLESME_SURUM)),
        )


class IosShortcuts:
    """
    Apple Shortcuts / companion URL ve payload yardımcıları.

    dry_run=True iken gerçek iPhone / Shortcuts uygulaması gerekmez;
    URL üretimi, ayrıştırma ve yerel sahte yanıt üretilir.
    """

    ad = "mobile.ios.shortcuts"
    surum = "0.1.0"

    def __init__(
        self,
        ayarlar: Optional[Ayarlar] = None,
        *,
        dry_run: bool = False,
        zorla_sahte: bool = False,
        scheme: Optional[str] = None,
        sozlesme: Optional[MobilKomutSozlesmesi] = None,
        kopru: Optional[Any] = None,
    ) -> None:
        self.ayarlar = ayarlar or global_ayarlar
        self.dry_run = bool(dry_run)
        self.zorla_sahte = bool(zorla_sahte)
        self.scheme = str(
            scheme
            or self.ayarlar.al("mobile.shortcuts.scheme", VARSAYILAN_SCHEME)
            or VARSAYILAN_SCHEME
        ).strip() or VARSAYILAN_SCHEME
        self.sozlesme = sozlesme or MobilKomutSozlesmesi(self.ayarlar)
        self.kopru = kopru
        self._motor = self._motor_sec()
        self._islenen: list[dict[str, Any]] = []

    @property
    def motor(self) -> str:
        return self._motor

    def _motor_sec(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.zorla_sahte:
            return "sahte"
        if self.kopru is not None:
            return "bridge"
        return "sahte"

    # ------------------------------------------------------------------ katalog

    def katalog(self) -> list[dict[str, Any]]:
        """Bilinen kısayol aksiyonlarının özeti."""
        sonuc: list[dict[str, Any]] = []
        for aksiyon in ShortcutAksiyon:
            komut = mobil_komuta(aksiyon)
            yon: Optional[str] = None
            if komut is not None:
                yon = komut_yonu(komut).value
            sonuc.append(
                {
                    "action": aksiyon.value,
                    "shortcut_name": kisayol_adi(aksiyon),
                    "command": komut.value if komut else None,
                    "direction": yon,
                    "dangerous": bool(komut and tehlikeli_mi(komut)),
                }
            )
        return sonuc

    # ------------------------------------------------------------------ payload

    def yuk_olustur(
        self,
        aksiyon: ShortcutAksiyonGirdi,
        *,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
        x_success: Optional[str] = None,
        x_error: Optional[str] = None,
        x_cancel: Optional[str] = None,
        kaynak: str = "shortcuts",
    ) -> ShortcutYuk:
        """Doğrulanmış ShortcutYuk üretir."""
        a = aksiyon_coz(aksiyon)
        return ShortcutYuk(
            aksiyon=a,
            args=dict(args or {}),
            cihaz_id=cihaz_id,
            token=token,
            x_success=x_success,
            x_error=x_error,
            x_cancel=x_cancel,
            kaynak=kaynak,
        )

    def yuk_to_istek(
        self,
        yuk: ShortcutYuk,
        *,
        dogrula: bool = True,
    ) -> MobilKomutIstegi:
        """ShortcutYuk → MobilKomutIstegi (pair/ping desteklenmez)."""
        komut = mobil_komuta(yuk.aksiyon)
        if komut is None:
            raise MobileBridgeError(
                f"Aksiyon mobil komuta cevrilemez: {yuk.aksiyon.value}",
                kod="MOB_0054",
                modul=self.ad,
                detay={"action": yuk.aksiyon.value},
            )
        return self.sozlesme.istek_olustur(
            komut,
            cihaz_id=yuk.cihaz_id,
            args=dict(yuk.args),
            corr_id=yuk.istek_id,
            dogrula=dogrula,
        )

    def istek_to_yuk(
        self,
        istek: MobilKomutIstegi,
        *,
        token: Optional[str] = None,
        kaynak: str = "bridge",
    ) -> ShortcutYuk:
        """MobilKomutIstegi → ShortcutYuk."""
        return ShortcutYuk(
            aksiyon=aksiyon_coz(istek.komut.value),
            args=dict(istek.args),
            istek_id=istek.istek_id,
            zaman=istek.zaman,
            cihaz_id=istek.cihaz_id,
            token=token,
            kaynak=kaynak,
        )

    # ------------------------------------------------------------------ URL üretimi

    def companion_url(
        self,
        aksiyon: ShortcutAksiyonGirdi,
        *,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
        istek_id: Optional[str] = None,
        x_success: Optional[str] = None,
        x_error: Optional[str] = None,
        x_cancel: Optional[str] = None,
    ) -> str:
        """
        Companion URL üretir.

        Örnek:
          whitecore://v1/command?action=find_phone&device_id=...&id=...
        """
        a = aksiyon_coz(aksiyon)
        params: dict[str, str] = {
            "action": a.value,
            "id": istek_id or uuid4().hex,
            "v": str(SHORTCUTS_SOZLESME_SURUM),
        }
        if cihaz_id:
            params["device_id"] = str(cihaz_id)
        if token:
            params["token"] = str(token)
        if args:
            for anahtar, deger in args.items():
                params[f"arg_{anahtar}"] = _deger_str(deger)
        if x_success:
            params["x-success"] = x_success
        if x_error:
            params["x-error"] = x_error
        if x_cancel:
            params["x-cancel"] = x_cancel
        return f"{self.scheme}://v1/command?{urlencode(params, quote_via=quote)}"

    def x_callback_url(
        self,
        aksiyon: ShortcutAksiyonGirdi,
        *,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
        x_success: str = "shortcuts://",
        x_error: str = "shortcuts://",
        x_cancel: Optional[str] = None,
    ) -> str:
        """x-callback-url yolunu kullanan companion URL."""
        a = aksiyon_coz(aksiyon)
        params: dict[str, str] = {
            "action": a.value,
            "id": uuid4().hex,
            "v": str(SHORTCUTS_SOZLESME_SURUM),
            "x-success": x_success,
            "x-error": x_error,
        }
        if x_cancel:
            params["x-cancel"] = x_cancel
        if cihaz_id:
            params["device_id"] = str(cihaz_id)
        if token:
            params["token"] = str(token)
        if args:
            for anahtar, deger in args.items():
                params[f"arg_{anahtar}"] = _deger_str(deger)
        return (
            f"{self.scheme}://x-callback-url/command?"
            f"{urlencode(params, quote_via=quote)}"
        )

    def shortcuts_calistir_url(
        self,
        aksiyon: ShortcutAksiyonGirdi,
        *,
        girdi_metni: Optional[str] = None,
        cihaz_id: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Apple Shortcuts run-shortcut URL'i.

        Örnek:
          shortcuts://run-shortcut?name=WhiteCore%20Find%20Phone&input=text&text=...
        """
        a = aksiyon_coz(aksiyon)
        ad = kisayol_adi(a)
        if girdi_metni is None:
            yuk = self.yuk_olustur(a, cihaz_id=cihaz_id, args=args)
            # Basit metin girdi: action=...&device_id=...
            parcalar = [f"action={a.value}", f"id={yuk.istek_id}"]
            if cihaz_id:
                parcalar.append(f"device_id={cihaz_id}")
            if args:
                for k, v in args.items():
                    parcalar.append(f"{k}={_deger_str(v)}")
            girdi_metni = "&".join(parcalar)
        params = {
            "name": ad,
            "input": "text",
            "text": girdi_metni,
        }
        return f"{APPLE_SHORTCUTS_SCHEME}://run-shortcut?{urlencode(params, quote_via=quote)}"

    def shortcuts_ac_url(self, aksiyon: ShortcutAksiyonGirdi) -> str:
        """Apple Shortcuts open-shortcut URL'i (düzenleme ekranı)."""
        ad = kisayol_adi(aksiyon)
        return (
            f"{APPLE_SHORTCUTS_SCHEME}://open-shortcut?"
            f"{urlencode({'name': ad}, quote_via=quote)}"
        )

    # ------------------------------------------------------------------ URL ayrıştırma

    def url_ayristir(self, url: str) -> ShortcutYuk:
        """
        whitecore:// veya shortcuts:// URL'sini ShortcutYuk'a çevirir.

        Desteklenen yollar:
          whitecore://v1/command?...
          whitecore://x-callback-url/command?...
          shortcuts://run-shortcut?name=...&text=action=find_phone&...
        """
        ham = str(url or "").strip()
        if not ham:
            raise MobileBridgeError(
                "URL bos olamaz",
                kod="MOB_0055",
                modul=self.ad,
            )
        parca = urlparse(ham)
        scheme = (parca.scheme or "").lower()
        query = parse_qs(parca.query, keep_blank_values=True)

        def _q(anahtar: str, varsayilan: Optional[str] = None) -> Optional[str]:
            degerler = query.get(anahtar)
            if not degerler:
                return varsayilan
            return unquote(degerler[0])

        if scheme == APPLE_SHORTCUTS_SCHEME:
            return self._ayristir_apple_shortcuts(query, _q)

        if scheme and scheme != self.scheme.lower():
            # Bilinen alternatif: yapılandırılmış scheme dışı whitecore
            if scheme != VARSAYILAN_SCHEME:
                raise MobileBridgeError(
                    f"Desteklenmeyen URL scheme: {scheme!r}",
                    kod="MOB_0056",
                    modul=self.ad,
                    detay={"scheme": scheme},
                )

        aksiyon_ham = _q("action") or _q("command")
        if not aksiyon_ham:
            raise MobileBridgeError(
                "URL icinde action yok",
                kod="MOB_0052",
                modul=self.ad,
            )

        args: dict[str, Any] = {}
        for anahtar, degerler in query.items():
            if anahtar.startswith("arg_") and degerler:
                args[anahtar[4:]] = _deger_coz(unquote(degerler[0]))

        return ShortcutYuk(
            aksiyon=aksiyon_coz(aksiyon_ham),
            args=args,
            istek_id=str(_q("id") or uuid4().hex),
            cihaz_id=_q("device_id"),
            token=_q("token"),
            x_success=_q("x-success") or _q("x_success"),
            x_error=_q("x-error") or _q("x_error"),
            x_cancel=_q("x-cancel") or _q("x_cancel"),
            kaynak="url",
        )

    def _ayristir_apple_shortcuts(
        self,
        query: dict[str, list[str]],
        _q: Any,
    ) -> ShortcutYuk:
        """shortcuts://run-shortcut metin girdisinden yük üretir."""
        metin = _q("text") or _q("input") or ""
        ad = _q("name") or ""
        aksiyon_ham: Optional[str] = None
        cihaz_id: Optional[str] = None
        istek_id: Optional[str] = None
        args: dict[str, Any] = {}

        if metin:
            # action=find_phone&device_id=... veya düz komut adı
            if "=" in metin:
                for parca in metin.split("&"):
                    if "=" not in parca:
                        continue
                    k, v = parca.split("=", 1)
                    k = k.strip().lower()
                    v = unquote(v.strip())
                    if k in {"action", "command"}:
                        aksiyon_ham = v
                    elif k in {"device_id", "cihaz_id"}:
                        cihaz_id = v
                    elif k == "id":
                        istek_id = v
                    else:
                        args[k] = _deger_coz(v)
            else:
                aksiyon_ham = metin.strip().lower()

        if not aksiyon_ham and ad:
            # Görünen addan ters eşle
            ad_norm = ad.strip().lower()
            for komut, kisayol in VARSAYILAN_KISAYOL_ADLARI.items():
                if kisayol.lower() == ad_norm:
                    aksiyon_ham = komut
                    break

        if not aksiyon_ham:
            raise MobileBridgeError(
                "shortcuts URL icinden action cozulemedi",
                kod="MOB_0052",
                modul=self.ad,
                detay={"name": ad, "text": metin[:80]},
            )

        return ShortcutYuk(
            aksiyon=aksiyon_coz(aksiyon_ham),
            args=args,
            istek_id=istek_id or uuid4().hex,
            cihaz_id=cihaz_id,
            kaynak="apple_shortcuts",
        )

    # ------------------------------------------------------------------ işleme (dry_run)

    async def isle(
        self,
        girdi: Union[str, ShortcutYuk, MobilKomutIstegi],
        *,
        dogrula: bool = True,
        cihaz_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        URL / yük / isteği işler; tek tip dict yanıt döner.

        - kopru varsa ve aksiyon mobil komuta çevrilebiliyorsa köprüye iletir
        - aksi halde dry_run / sahte yerel yanıt üretir
        """
        if isinstance(girdi, str):
            yuk = self.url_ayristir(girdi)
        elif isinstance(girdi, MobilKomutIstegi):
            yuk = self.istek_to_yuk(girdi)
        elif isinstance(girdi, ShortcutYuk):
            yuk = girdi
        else:
            raise MobileBridgeError(
                "Girdi URL, ShortcutYuk veya MobilKomutIstegi olmali",
                kod="MOB_0057",
                modul=self.ad,
            )

        if cihaz_id and not yuk.cihaz_id:
            yuk.cihaz_id = cihaz_id

        # pair / ping — yerel companion yanıtı (MobilKomut değil)
        if yuk.aksiyon is ShortcutAksiyon.PAIR:
            sonuc = self._yanit_pair(yuk)
        elif yuk.aksiyon is ShortcutAksiyon.PING:
            sonuc = self._yanit_ping(yuk)
        else:
            yanit = await self._isle_komut(yuk, dogrula=dogrula)
            sonuc = self._yanit_dict(yanit, aksiyon=yuk.aksiyon.value)

        self._islenen.append(
            {
                "action": yuk.aksiyon.value,
                "status": sonuc.get("status"),
                "device_id": yuk.cihaz_id,
                "request_id": yuk.istek_id,
                "engine": self._motor,
                "ts": _utc_iso(),
            }
        )
        audit_yaz(
            "ios.shortcuts.handled",
            modul=self.ad,
            detay={
                "action": yuk.aksiyon.value,
                "status": sonuc.get("status"),
                "device_id": yuk.cihaz_id,
                "engine": self._motor,
                "dry_run": self.dry_run,
            },
        )
        return sonuc

    async def _isle_komut(
        self,
        yuk: ShortcutYuk,
        *,
        dogrula: bool,
    ) -> MobilKomutYaniti:
        istek = self.yuk_to_istek(yuk, dogrula=dogrula)
        # İstek id'sini shortcut id ile hizala
        istek.istek_id = yuk.istek_id

        if self.kopru is not None and getattr(self.kopru, "calisiyor", False):
            cid = yuk.cihaz_id or ""
            if not cid:
                raise MobileBridgeError(
                    "device_id zorunlu (kopru ile isleme)",
                    kod="MOB_0058",
                    modul=self.ad,
                )
            return await self.kopru.komut_gonder(
                cid, istek, dogrula=dogrula
            )

        return self._yerel_yanit(istek)

    def _yanit_dict(
        self,
        yanit: MobilKomutYaniti,
        *,
        aksiyon: str,
    ) -> dict[str, Any]:
        veri = yanit.to_dict()
        veri["ok"] = yanit.basarili_mi
        veri["action"] = aksiyon
        veri["engine"] = self._motor
        veri["dry_run"] = self.dry_run
        veri["via"] = "shortcuts"
        if yanit.durum is not KomutDurum.OK and not yanit.basarili_mi:
            veri.setdefault("error", yanit.mesaj or yanit.durum.value)
        return veri

    def _yerel_yanit(self, istek: MobilKomutIstegi) -> MobilKomutYaniti:
        """dry_run / sahte yerel yanıt (iPhone yok)."""
        k = istek.komut
        if k is MobilKomut.FIND_PHONE:
            return self.sozlesme.yanit_ok(
                k,
                mesaj="Find phone (shortcuts dry_run)",
                veri={
                    "played": True,
                    "vibrate": bool(istek.args.get("vibrate", True)),
                    "sound": bool(istek.args.get("sound", True)),
                    "engine": self._motor,
                    "via": "shortcuts",
                },
                istek_id=istek.istek_id,
                cihaz_id=istek.cihaz_id,
            )
        if k is MobilKomut.BATTERY_STATUS:
            return self.sozlesme.yanit_ok(
                k,
                mesaj="Battery (shortcuts dry_run)",
                veri={
                    "percent": int(istek.args.get("percent", 80)),
                    "charging": bool(istek.args.get("charging", False)),
                    "low_power": False,
                    "engine": self._motor,
                    "via": "shortcuts",
                },
                istek_id=istek.istek_id,
                cihaz_id=istek.cihaz_id,
            )
        if k is MobilKomut.SEND_NOTIFICATION:
            return self.sozlesme.yanit_ok(
                k,
                mesaj="Notification (shortcuts dry_run)",
                veri={
                    "delivered": True,
                    "title": str(istek.args.get("title") or "WhiteCore"),
                    "body": str(istek.args.get("body") or ""),
                    "engine": self._motor,
                    "via": "shortcuts",
                },
                istek_id=istek.istek_id,
                cihaz_id=istek.cihaz_id,
            )
        if istek.yon is KomutYon.PHONE_TO_PC:
            # Tehlikeli komutlar dry_run'da pending/ok simülasyonu
            if tehlikeli_mi(k) and not self.dry_run and not self.zorla_sahte:
                return self.sozlesme.yanit_hata(
                    k,
                    "Onay gerekli (shortcuts)",
                    durum=KomutDurum.BEKLIYOR,
                    istek_id=istek.istek_id,
                    cihaz_id=istek.cihaz_id,
                    veri={"require_confirm": True, "via": "shortcuts"},
                )
            return self.sozlesme.yanit_ok(
                k,
                mesaj=f"{k.value} kuyruga alindi (shortcuts dry_run)",
                veri={
                    "queued": True,
                    "command": k.value,
                    "engine": self._motor,
                    "via": "shortcuts",
                },
                istek_id=istek.istek_id,
                cihaz_id=istek.cihaz_id,
            )
        return self.sozlesme.yanit_ok(
            k,
            mesaj=f"{k.value} (shortcuts dry_run)",
            veri={"ok": True, "engine": self._motor, "via": "shortcuts"},
            istek_id=istek.istek_id,
            cihaz_id=istek.cihaz_id,
        )

    def _yanit_pair(self, yuk: ShortcutYuk) -> dict[str, Any]:
        """Companion eşleştirme sahte yanıtı (MobilKomut değil)."""
        return {
            "ok": True,
            "action": ShortcutAksiyon.PAIR.value,
            "status": KomutDurum.OK.value,
            "message": "Pair (shortcuts dry_run)",
            "data": {
                "paired": True,
                "device_id": yuk.cihaz_id,
                "token_accepted": bool(yuk.token),
                "engine": self._motor,
                "via": "shortcuts",
            },
            "id": yuk.istek_id,
            "device_id": yuk.cihaz_id,
            "engine": self._motor,
            "dry_run": self.dry_run,
            "via": "shortcuts",
            "ts": _utc_iso(),
        }

    def _yanit_ping(self, yuk: ShortcutYuk) -> dict[str, Any]:
        return {
            "ok": True,
            "action": ShortcutAksiyon.PING.value,
            "status": KomutDurum.OK.value,
            "message": "Pong (shortcuts)",
            "data": {
                "pong": True,
                "engine": self._motor,
                "via": "shortcuts",
                "ts": _utc_iso(),
            },
            "id": yuk.istek_id,
            "device_id": yuk.cihaz_id,
            "engine": self._motor,
            "dry_run": self.dry_run,
            "via": "shortcuts",
            "ts": _utc_iso(),
        }

    def islenenleri_cek(self) -> list[dict[str, Any]]:
        """İşlenen shortcut kayıtlarını alıp temizler (test)."""
        items = list(self._islenen)
        self._islenen.clear()
        return items

    def durum(self) -> dict[str, Any]:
        """Modül durum özeti."""
        return {
            "module": self.ad,
            "engine": self._motor,
            "dry_run": self.dry_run,
            "scheme": self.scheme,
            "catalog_size": len(ShortcutAksiyon),
            "handled": len(self._islenen),
            "bridge_attached": self.kopru is not None,
            "timestamp": _utc_iso(),
        }


def _deger_str(deger: Any) -> str:
    if isinstance(deger, bool):
        return "true" if deger else "false"
    return str(deger)


def _deger_coz(metin: str) -> Any:
    alt = metin.strip().lower()
    if alt == "true":
        return True
    if alt == "false":
        return False
    try:
        if "." in metin:
            return float(metin)
        return int(metin)
    except ValueError:
        return metin


def ios_shortcuts_olustur(
    *,
    dry_run: bool = True,
    zorla_sahte: bool = False,
    ayarlar: Optional[Ayarlar] = None,
    scheme: Optional[str] = None,
    kopru: Optional[Any] = None,
) -> IosShortcuts:
    """Test / demo için hazır IosShortcuts üretir."""
    return IosShortcuts(
        ayarlar,
        dry_run=dry_run,
        zorla_sahte=zorla_sahte,
        scheme=scheme,
        kopru=kopru,
    )


__all__ = [
    "SHORTCUTS_SOZLESME_SURUM",
    "VARSAYILAN_SCHEME",
    "APPLE_SHORTCUTS_SCHEME",
    "VARSAYILAN_KISAYOL_ADLARI",
    "ShortcutAksiyon",
    "ShortcutYuk",
    "IosShortcuts",
    "aksiyon_coz",
    "kisayol_adi",
    "mobil_komuta",
    "ios_shortcuts_olustur",
]
