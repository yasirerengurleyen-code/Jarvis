(() => {
  const $ = (id) => document.getElementById(id);
  const rozet = $("rozet");
  const hata = $("hata");
  const durumMetin = $("durum-metin");
  const ekranBaglan = $("ekran-baglan");
  const ekranSohbet = $("ekran-sohbet");
  const mesajlar = $("mesajlar");

  let ws = null;
  let token = "";
  let deviceId = "";
  let wsUrl = "";

  function setOnline(online, text) {
    rozet.textContent = online ? "● ONLINE" : "○ OFFLINE";
    rozet.className = "rozet " + (online ? "online" : "offline");
    if (text) durumMetin.textContent = text;
  }

  function ekleMesaj(kim, metin, sinif) {
    const div = document.createElement("div");
    div.className = "msg " + (sinif || "");
    div.innerHTML = `<span class="kim">${kim}</span> — ${escapeHtml(metin)}`;
    mesajlar.appendChild(div);
    mesajlar.scrollTop = mesajlar.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function zarf(type, payload, extra) {
    return JSON.stringify({
      magic: "WHITECORE",
      v: 1,
      type,
      id: crypto.randomUUID().replace(/-/g, ""),
      ts: new Date().toISOString(),
      device_id: deviceId || undefined,
      payload: payload || {},
      ...(extra || {}),
    });
  }

  function qs() {
    const u = new URL(location.href);
    const hash = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    return {
      code: u.searchParams.get("code") || hash.get("code") || "",
      token: u.searchParams.get("token") || hash.get("token") || "",
      host: u.searchParams.get("host") || hash.get("host") || location.hostname,
      ws: u.searchParams.get("ws_port") || hash.get("ws_port") || "",
    };
  }

  async function durumCek() {
    try {
      const r = await fetch("/api/status");
      const j = await r.json();
      if (j.online) setOnline(false, `PC hazır · ${j.lan_ip || ""}`);
    } catch (_) {
      setOnline(false, "PC bulunamadı");
    }
  }

  async function pair(code, name) {
    const r = await fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, name }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "Eşleştirme başarısız");
    return j;
  }

  function wsBaglan(url, authToken) {
    return new Promise((resolve, reject) => {
      const sock = new WebSocket(url);
      let authed = false;
      sock.onopen = () => {
        durumMetin.textContent = "WS açık · auth…";
      };
      sock.onerror = () => reject(new Error("WebSocket hatası"));
      sock.onclose = () => {
        setOnline(false, "Bağlantı koptu");
        ekranSohbet.classList.add("gizli");
        ekranBaglan.classList.remove("gizli");
      };
      sock.onmessage = (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        const type = msg.type;
        if (type === "hello") {
          sock.send(zarf("hello", { role: "phone", name: $("ad").value || "iPhone" }));
          sock.send(zarf("auth", { token: authToken }));
          return;
        }
        if (type === "auth_ok") {
          authed = true;
          deviceId = (msg.payload && msg.payload.device_id) || deviceId;
          setOnline(true, "Telefon ONLINE");
          ekleMesaj("SYS", "Jarvis’e bağlandınız.", "sys");
          resolve(sock);
          return;
        }
        if (type === "auth_fail") {
          const p = msg.payload || {};
          reject(new Error(p.reason || p.message || "Auth başarısız"));
          sock.close();
          return;
        }
        if (type === "ping") {
          sock.send(zarf("pong", {}, { corr_id: msg.id }));
          return;
        }
        if (type === "chat_sync") {
          const text = (msg.payload && (msg.payload.text || msg.payload.content)) || "";
          const from = (msg.payload && msg.payload.from) || "J.A.R.V.I.S.";
          if (text) ekleMesaj(from, text, "sys");
          return;
        }
        if (type === "notification") {
          const text = (msg.payload && msg.payload.message) || "Bildirim";
          ekleMesaj("SYS", text, "sys");
        }
      };
      setTimeout(() => {
        if (!authed) reject(new Error("Auth zaman aşımı"));
      }, 8000);
    });
  }

  async function baglan() {
    hata.textContent = "";
    const code = ($("kod").value || "").trim();
    const name = ($("ad").value || "iPhone").trim();
    if (!code && !token) {
      hata.textContent = "Kod gerekli";
      return;
    }
    try {
      $("btn-baglan").disabled = true;
      let authToken = token;
      let url = wsUrl;
      if (code) {
        const j = await pair(code, name);
        authToken = j.token || authToken;
        deviceId = j.device_id || "";
        url = j.ws_url || url;
      }
      if (!url) {
        const host = location.hostname;
        const port = qs().ws || "8742";
        url = `ws://${host}:${port}`;
      }
      if (!authToken) throw new Error("Token yok — kod ile bağlanın");
      ws = await wsBaglan(url, authToken);
      token = authToken;
      wsUrl = url;
      ekranBaglan.classList.add("gizli");
      ekranSohbet.classList.remove("gizli");
    } catch (e) {
      hata.textContent = e.message || String(e);
      setOnline(false, "Bağlantı başarısız");
    } finally {
      $("btn-baglan").disabled = false;
    }
  }

  function gonder() {
    const text = ($("mesaj").value || "").trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(
      zarf("chat_sync", {
        text,
        content: text,
        from: $("ad").value || "iPhone",
        direction: "phone_to_pc",
      })
    );
    ekleMesaj("Siz", text, "me");
    $("mesaj").value = "";
  }

  $("btn-baglan").addEventListener("click", baglan);
  $("btn-gonder").addEventListener("click", gonder);
  $("mesaj").addEventListener("keydown", (e) => {
    if (e.key === "Enter") gonder();
  });
  $("btn-kop").addEventListener("click", () => {
    if (ws) ws.close();
    ws = null;
    setOnline(false, "Koptu");
    ekranSohbet.classList.add("gizli");
    ekranBaglan.classList.remove("gizli");
  });

  // QR / deep link parametreleri
  const q = qs();
  if (q.code) $("kod").value = q.code;
  if (q.token) token = q.token;
  if (q.ws) {
    wsUrl = `ws://${q.host || location.hostname}:${q.ws}`;
  }

  durumCek();
  if (q.code || q.token) {
    // Otomatik dene
    setTimeout(baglan, 300);
  }
})();
