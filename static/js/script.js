// Campos dinámicos "Otro" + "+ Agregar otro" (formulario de registro y revisión)
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-otros]").forEach((box) => {
    const lista = box.querySelector(".otros-list");
    const nombre = box.dataset.otrosName;
    const chk = box.dataset.otrosFor ? document.getElementById(box.dataset.otrosFor) : null;

    const nuevo = (valor = "") => {
      const fila = document.createElement("div");
      fila.className = "otros-fila";
      fila.innerHTML = `<input type="text" name="${nombre}" maxlength="60" placeholder="Ej. Tunas, cáscara de naranja…" aria-label="Otro ingrediente">
                        <button type="button" class="quitar" aria-label="Quitar ingrediente">✕</button>`;
      fila.querySelector("input").value = valor;
      fila.querySelector(".quitar").onclick = () => {
        if (lista.children.length > 1) fila.remove(); else fila.querySelector("input").value = "";
      };
      lista.appendChild(fila);
      return fila;
    };
    if (!lista.children.length) nuevo();
    lista.querySelectorAll(".quitar").forEach((b) => (b.onclick = () => {
      const f = b.parentElement;
      if (lista.children.length > 1) f.remove(); else f.querySelector("input").value = "";
    }));
    box.querySelector("[data-add-otro]").onclick = () => nuevo().querySelector("input").focus();

    if (chk) {
      const sync = () => {
        box.hidden = !chk.checked;
        lista.querySelector("input").required = chk.checked;
      };
      chk.addEventListener("change", sync);
      sync();
    }
  });
});

// Fotografía: elegir archivo, vista previa y cámara
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("fotografia");
  if (!input) return;
  const captura = document.getElementById("fotoCaptura");
  const vista = document.getElementById("fotoVista");
  const nombre = document.getElementById("fotoNombre");
  const modal = document.getElementById("camaraModal");
  const video = document.getElementById("camaraVideo");
  let stream = null;

  const mostrar = () => {
    const f = input.files[0];
    if (!f) { vista.hidden = true; nombre.textContent = "Ningún archivo seleccionado"; return; }
    nombre.textContent = f.name;
    if (vista.src) URL.revokeObjectURL(vista.src);
    vista.src = URL.createObjectURL(f);
    vista.hidden = false;
  };
  const asignar = (file) => {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    mostrar();
  };
  input.addEventListener("change", mostrar);
  captura.addEventListener("change", () => { if (captura.files[0]) asignar(captura.files[0]); });

  const cerrar = () => {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null; video.srcObject = null; modal.hidden = true;
  };
  document.getElementById("btnCerrarCamara").onclick = cerrar;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) cerrar(); });

  document.getElementById("btnCamara").onclick = async () => {
    // Sin cámara web disponible (p. ej. página sin HTTPS): usa la cámara del teléfono
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { captura.click(); return; }
    modal.hidden = false;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      video.srcObject = stream;
    } catch (e) {
      cerrar();
      captura.click();
    }
  };

  document.getElementById("btnCapturar").onclick = () => {
    if (!video.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0);
    c.toBlob((blob) => {
      if (blob) asignar(new File([blob], `foto_${Date.now()}.jpg`, { type: "image/jpeg" }));
      cerrar();
    }, "image/jpeg", 0.9);
  };
});

// Si una fotografía no se puede cargar, mostrar un aviso en vez de una imagen rota
(() => {
  const reemplazar = (img) => {
    if (img.dataset.fallo) return;
    img.dataset.fallo = "1";
    const aviso = document.createElement("span");
    aviso.className = "sin-foto";
    aviso.textContent = "Foto no disponible";
    img.replaceWith(aviso);
  };
  document.addEventListener("error", (e) => {
    if (e.target.tagName === "IMG" && e.target.hasAttribute("data-foto")) reemplazar(e.target);
  }, true);
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("img[data-foto]").forEach((i) => {
      if (i.complete && i.naturalWidth === 0) reemplazar(i);
    });
  });
})();
