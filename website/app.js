(() => {
  const panelPc = document.getElementById("panel-pc");
  const panelTelefon = document.getElementById("panel-telefon");
  const body = document.body;

  function kapat() {
    panelPc.hidden = true;
    panelTelefon.hidden = true;
    body.classList.remove("panel-acik");
  }

  function ac(hedef) {
    kapat();
    const panel = hedef === "pc" ? panelPc : panelTelefon;
    panel.hidden = false;
    body.classList.add("panel-acik");
    panel.querySelector(".geri")?.focus();
  }

  document.getElementById("btn-pc")?.addEventListener("click", () => ac("pc"));
  document.getElementById("btn-telefon")?.addEventListener("click", () => ac("telefon"));

  document.querySelectorAll("[data-geri]").forEach((btn) => {
    btn.addEventListener("click", kapat);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") kapat();
  });

  panelPc?.addEventListener("click", (e) => {
    if (e.target === panelPc) kapat();
  });
  panelTelefon?.addEventListener("click", (e) => {
    if (e.target === panelTelefon) kapat();
  });
})();
