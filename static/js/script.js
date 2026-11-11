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


// =====================================================================
//  MODO SIN CONEXIÓN: login offline, cola de compostas y sincronización
// =====================================================================
(() => {
  const C = (window.Compostaje = {});

  // ---- SHA-256 en JavaScript puro (crypto.subtle no existe en páginas http://192.168.x.x) ----
  const sha256hex = (str) => {
    const enc=new TextEncoder().encode(str);
    const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const l=enc.length, n=((l+9+63)>>6)<<6, b=new Uint8Array(n);
    b.set(enc); b[l]=0x80;
    const dv=new DataView(b.buffer);
    dv.setUint32(n-8,Math.floor(l*8/0x100000000)); dv.setUint32(n-4,(l*8)>>>0);
    const w=new Uint32Array(64), r=(x,k)=>(x>>>k)|(x<<(32-k));
    for(let o=0;o<n;o+=64){
      for(let i=0;i<16;i++) w[i]=dv.getUint32(o+i*4);
      for(let i=16;i<64;i++){
        const s0=r(w[i-15],7)^r(w[i-15],18)^(w[i-15]>>>3), s1=r(w[i-2],17)^r(w[i-2],19)^(w[i-2]>>>10);
        w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;
      }
      let [a,bb,c,d,e,f,g,h]=H;
      for(let i=0;i<64;i++){
        const S1=r(e,6)^r(e,11)^r(e,25), ch=(e&f)^(~e&g), t1=(h+S1+ch+K[i]+w[i])>>>0;
        const S0=r(a,2)^r(a,13)^r(a,22), mj=(a&bb)^(a&c)^(bb&c), t2=(S0+mj)>>>0;
        h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=bb;bb=a;a=(t1+t2)>>>0;
      }
      H[0]=(H[0]+a)>>>0;H[1]=(H[1]+bb)>>>0;H[2]=(H[2]+c)>>>0;H[3]=(H[3]+d)>>>0;
      H[4]=(H[4]+e)>>>0;H[5]=(H[5]+f)>>>0;H[6]=(H[6]+g)>>>0;H[7]=(H[7]+h)>>>0;
    }
    return H.map(x=>x.toString(16).padStart(8,'0')).join('');
  };

  const aleatorio = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
  const hashCred = (nc, pw, salt) => {
    let h = sha256hex(`${salt}:${nc}:${pw}`);
    for (let i = 0; i < 2000; i++) h = sha256hex(h + salt);
    return h;
  };
  const leerUsuarios = () => { try { return JSON.parse(localStorage.getItem("offline_users") || "{}"); } catch (e) { return {}; } };
  const guardarUsuarios = (u) => { try { localStorage.setItem("offline_users", JSON.stringify(u)); } catch (e) {} };

  // Al enviar el login CON internet: se calcula la verificación y se guarda temporalmente.
  // Solo se vuelve permanente si el servidor confirma que el login fue correcto.
  C.prepararLogin = (nc, pw) => {
    const salt = aleatorio();
    try { sessionStorage.setItem("pending_cred", JSON.stringify({ nc, salt, hash: hashCred(nc, pw, salt), t: Date.now() })); } catch (e) {}
  };
  C.loginOffline = (nc, pw) => {
    const u = leerUsuarios()[nc];
    if (!u) return { ok: false, motivo: "nuevo" };
    if (hashCred(nc, pw, u.salt) !== u.hash) return { ok: false, motivo: "clave" };
    localStorage.setItem("offline_current", nc);
    return { ok: true, nombre: u.nombre };
  };
  C.usuarioOffline = () => {
    const nc = localStorage.getItem("offline_current");
    const u = nc && leerUsuarios()[nc];
    return u ? { nc, nombre: u.nombre } : null;
  };
  C.salirOffline = () => localStorage.removeItem("offline_current");
  C.info = () => document.getElementById("sesion-info");

  // Promover credenciales: la página ya cargó con sesión iniciada del mismo número de control
  const promover = () => {
    let pend = null;
    try { pend = JSON.parse(sessionStorage.getItem("pending_cred") || "null"); } catch (e) {}
    const info = C.info();
    if (pend && info && info.dataset.rol === "estudiante" && info.dataset.nc === pend.nc && Date.now() - pend.t < 5 * 60 * 1000) {
      const us = leerUsuarios();
      us[pend.nc] = { nombre: info.dataset.nombre, salt: pend.salt, hash: pend.hash };
      guardarUsuarios(us);
    }
    if (pend) sessionStorage.removeItem("pending_cred");
  };

  // ---- IndexedDB: cola de compostas y de reportes (soporta fotos grandes) ----
  const abrirDB = () => new Promise((res, rej) => {
    const r = indexedDB.open("compostaje_offline", 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore("pendientes", { keyPath: "idLocal" });
      r.result.createObjectStore("reportes", { keyPath: "idLocal" });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  const tx = async (almacen, modo, fn) => {
    const db = await abrirDB();
    return new Promise((res, rej) => {
      const t = db.transaction(almacen, modo);
      const rq = fn(t.objectStore(almacen));
      t.oncomplete = () => { db.close(); res(rq && rq.result); };
      t.onerror = t.onabort = () => { db.close(); rej(t.error); };
    });
  };
  const almacen = (nombre) => ({
    agregar: (it) => tx(nombre, "readwrite", (s) => s.put(it)),
    todos: () => tx(nombre, "readonly", (s) => s.getAll()),
    borrar: (id) => tx(nombre, "readwrite", (s) => s.delete(id)),
  });
  C.cola = almacen("pendientes");
  C.colaReportes = almacen("reportes");
  C.nuevoId = () => `${Date.now().toString(36)}-${aleatorio()}`;

  // Comprobar que realmente hay servidor (Se eliminó la revisión de navigator.onLine)
  C.hayServidor = async () => {
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 4000);
      const r = await fetch("/ping", { cache: "no-store", signal: ctl.signal });
      clearTimeout(t);
      return r.ok;
    } catch (e) { return false; }
  };

  // Compostas guardadas por la versión anterior (localStorage) -> IndexedDB
  const migrarLegado = async () => {
    let viejos = [];
    try { viejos = JSON.parse(localStorage.getItem("compostas_pendientes") || "[]"); } catch (e) {}
    if (!viejos.length) { localStorage.removeItem("compostas_pendientes"); return; }
    try {
      for (const v of viejos) {
        let foto = null;
        if (v.fotoBase64) foto = await (await fetch(v.fotoBase64)).blob();
        await C.cola.agregar({ idLocal: C.nuevoId(), nc: "", peso: v.peso, ingredientes: v.ingredientes || [],
          otros: v.otrosIngredientes || [], fecha: v.fecha, foto, fotoNombre: v.fotoNombre || "offline.jpg" });
      }
      localStorage.removeItem("compostas_pendientes");
    } catch (e) { console.warn("No se pudo migrar la cola anterior", e); }
  };

  // ---- Aviso en pantalla ----
  const aviso = (texto, tipo = "info", extra) => {
    let wrap = document.getElementById("aviso-wrap");
    if (!texto) { if (wrap) wrap.remove(); return; }
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "aviso-wrap";
      wrap.className = "flashes";
      const main = document.querySelector("main");
      (main || document.body).prepend(wrap);
    }
    wrap.innerHTML = "";
    const d = document.createElement("div");
    d.className = `alert alert-${tipo}`;
    d.textContent = texto;
    if (extra) { d.append(" "); d.append(extra); }
    wrap.append(d);
  };
  const refrescarAviso = async () => {
    let todos = [];
    try { todos = await C.cola.todos(); } catch (e) { return; }
    if (!todos.length) { aviso(null); return; }
    const conError = todos.filter((t) => t.error);
    const info = C.info();
    const n = todos.length;
    let texto;
    if (!navigator.onLine) texto = `📴 Tienes ${n} composta(s) guardada(s) en este dispositivo. Se enviarán cuando recuperes internet.`;
    else if (!info || info.dataset.rol !== "estudiante") texto = `📤 Tienes ${n} composta(s) guardada(s) en este dispositivo. Inicia sesión (con internet) para enviarlas.`;
    else texto = `📤 Tienes ${n} composta(s) pendiente(s) de enviar.`;
    let extra = null;
    if (conError.length) {
      texto += ` ${conError.length} tiene(n) datos inválidos: ${conError[0].error}`;
      extra = document.createElement("button");
      extra.type = "button"; extra.className = "btn ghost small"; extra.textContent = "Descartar las inválidas";
      extra.onclick = async () => { for (const t of conError) await C.cola.borrar(t.idLocal); refrescarAviso(); };
    }
    aviso(texto, "info", extra);
  };
  C.refrescarAviso = refrescarAviso;

  // ---- Reportes de problemas pendientes ----
  const enviarReportes = async () => {
    let lista = [];
    try { lista = await C.colaReportes.todos(); } catch (e) { return; }
    for (const r of lista) {
      try {
        const fd = new FormData();
        Object.entries(r.campos).forEach(([k, v]) => fd.append(k, v));
        if (r.imagen) fd.append("imagen", r.imagen, "captura.jpg");
        const resp = await fetch("/reportar_problema", { method: "POST", body: fd, credentials: "same-origin" });
        if (resp.ok || resp.status === 400) await C.colaReportes.borrar(r.idLocal);
        else break;
      } catch (e) { break; }
    }
  };

  // ---- Sincronización de compostas ----
  let sincronizando = false;
  C.sincronizar = async () => {
    if (sincronizando) return;
    if (navigator.onLine) await enviarReportes();
    await migrarLegado();
    await refrescarAviso();
    const info = C.info();
    if (!navigator.onLine || !info || info.dataset.rol !== "estudiante") return;
    sincronizando = true;
    let enviadas = 0;
    try {
      const todos = await C.cola.todos();
      for (const it of todos) {
        if (it.error) continue;
        if (it.nc && it.nc !== info.dataset.nc) continue; // es de otro usuario de este dispositivo
        const fd = new FormData();
        fd.append("idLocal", it.idLocal);
        fd.append("nc", it.nc || "");
        fd.append("peso", it.peso);
        fd.append("fecha", it.fecha || "");
        (it.ingredientes || []).forEach((i) => fd.append("ingredientes", i));
        (it.otros || []).forEach((o) => fd.append("otrosIngredientes", o));
        if (it.foto) fd.append("fotografia", it.foto, it.fotoNombre || "offline.jpg");
        let r;
        try { r = await fetch("/sync_offline_composta", { method: "POST", body: fd, credentials: "same-origin" }); }
        catch (e) { break; }
        if (r.ok) { await C.cola.borrar(it.idLocal); enviadas++; }
        else if (r.status === 400) {
          let msg = "Datos inválidos";
          try { msg = (await r.json()).error || msg; } catch (e) {}
          it.error = msg; await C.cola.agregar(it);
        } else break; // 401/403/5xx: se reintenta luego
      }
    } finally { sincronizando = false; }
    if (enviadas) {
      aviso(`🎉 Se enviaron ${enviadas} composta(s) guardada(s) sin conexión.`, "success");
      setTimeout(refrescarAviso, 6000);
      if (location.pathname === "/mis_compostas") setTimeout(() => location.reload(), 1500);
    } else await refrescarAviso();
  };

  document.addEventListener("DOMContentLoaded", () => {
    promover();
    C.sincronizar();
  });
  window.addEventListener("online", () => setTimeout(C.sincronizar, 800));
  window.addEventListener("offline", refrescarAviso);
  setInterval(() => { if (navigator.onLine) C.sincronizar(); }, 60000);
})();

// =====================================================================
//  REPORTAR PROBLEMA (captura de pantalla + descripción -> correo)
// =====================================================================
(() => {
  // Guarda los últimos errores de JavaScript para adjuntarlos al reporte
  let errores = [];
  try { errores = JSON.parse(sessionStorage.getItem("errores_js") || "[]"); } catch (e) {}
  const anotar = (m) => {
    errores.push({ t: new Date().toISOString(), p: location.pathname, m: String(m).slice(0, 300) });
    while (errores.length > 10) errores.shift();
    try { sessionStorage.setItem("errores_js", JSON.stringify(errores)); } catch (e) {}
  };
  window.addEventListener("error", (e) => anotar(`${e.message} (${(e.filename || "").split("/").pop()}:${e.lineno})`));
  window.addEventListener("unhandledrejection", (e) => anotar("Promesa rechazada: " + ((e.reason && e.reason.message) || e.reason)));

  const cargarScript = (src) => new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = src; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });
  const conTiempo = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("tiempo")), ms))]);

  // Captura automática de lo que se ve en pantalla (necesita internet para bajar html2canvas)
  const capturarPantalla = async () => {
    if (!navigator.onLine) return null;
    try {
      if (!window.html2canvas) await conTiempo(cargarScript("https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"), 6000);
      const canvas = await conTiempo(window.html2canvas(document.body, {
        useCORS: true, logging: false, scale: Math.min(1, 1000 / window.innerWidth) || 1,
        x: window.scrollX, y: window.scrollY, width: window.innerWidth, height: window.innerHeight,
        windowWidth: document.documentElement.clientWidth, windowHeight: window.innerHeight,
        ignoreElements: (el) => el.id === "btnReportar" || el.id === "reporteModal",
      }), 10000);
      return await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.75));
    } catch (e) { return null; }
  };

  // Reduce una imagen subida por el usuario (las capturas del celular pesan mucho)
  const reducir = (blob, max = 1400) => new Promise((res) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob((b) => res(b || blob), "image/jpeg", 0.75);
    };
    img.onerror = () => { URL.revokeObjectURL(url); res(null); };
    img.src = url;
  });

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("btnReportar");
    if (!btn) return;
    const modal = document.createElement("div");
    modal.id = "reporteModal"; modal.className = "modal"; modal.hidden = true;
    modal.setAttribute("role", "dialog"); modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `
      <div class="modal-caja reporte-caja">
        <h3 style="margin:0 0 4px">🐞 Reportar un problema</h3>
        <p class="hint" style="margin:0 0 12px">Cuéntanos qué pasó. Se enviará al responsable del sistema junto con una captura de pantalla.</p>
        <label for="repTexto">¿Qué problema tuviste?</label>
        <textarea id="repTexto" rows="4" maxlength="2000" placeholder="Ej. Al presionar Registrar composta me salió un error…"></textarea>
        <div class="rep-captura">
          <span class="label-like">Captura de pantalla</span>
          <img id="repVista" alt="Captura del problema" hidden>
          <small id="repEstado"></small>
          <label class="btn ghost small" for="repArchivo" style="margin-top:8px;width:fit-content">📎 Adjuntar mi propia captura</label>
          <input type="file" id="repArchivo" accept="image/*" hidden>
          <button type="button" class="btn ghost small" id="repQuitar" style="width:fit-content" hidden>Quitar captura</button>
        </div>
        <p id="repMsg" class="hint" role="status"></p>
        <div class="modal-botones">
          <button type="button" class="btn" id="repEnviar">Enviar reporte</button>
          <button type="button" class="btn ghost" id="repCancelar">Cancelar</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    const $ = (id) => document.getElementById(id);
    let imagen = null;
    const mostrarImagen = () => {
      if ($("repVista").src) URL.revokeObjectURL($("repVista").src);
      if (imagen) { $("repVista").src = URL.createObjectURL(imagen); $("repVista").hidden = false; $("repQuitar").hidden = false; $("repEstado").textContent = ""; }
      else { $("repVista").hidden = true; $("repQuitar").hidden = true; $("repEstado").textContent = "No se pudo capturar la pantalla automáticamente. Puedes adjuntar tu propia captura (opcional)."; }
    };
    const cerrar = () => { modal.hidden = true; $("repMsg").textContent = ""; };
    $("repCancelar").onclick = cerrar;
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) cerrar(); });
    $("repQuitar").onclick = () => { imagen = null; mostrarImagen(); };
    $("repArchivo").onchange = async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      imagen = await reducir(f);
      mostrarImagen();
      e.target.value = "";
    };

    btn.onclick = async () => {
      const textoOriginal = btn.textContent;
      btn.disabled = true; btn.textContent = "📸 Capturando…";
      imagen = await capturarPantalla();
      btn.disabled = false; btn.textContent = textoOriginal;
      $("repTexto").value = "";
      mostrarImagen();
      modal.hidden = false;
      $("repTexto").focus();
    };

    $("repEnviar").onclick = async () => {
      const descripcion = $("repTexto").value.trim();
      if (descripcion.length < 5) { $("repMsg").textContent = "Describe brevemente el problema."; return; }
      const info = document.getElementById("sesion-info");
      const offUser = window.Compostaje && window.Compostaje.usuarioOffline();
      const campos = {
        idLocal: window.Compostaje.nuevoId(),
        descripcion,
        url: location.href,
        userAgent: navigator.userAgent,
        pantalla: `${window.innerWidth}x${window.innerHeight}`,
        hora: new Date().toISOString(),
        conexion: navigator.onLine ? "con internet" : "sin internet",
        usuarioNc: (info && info.dataset.nc) || (offUser && offUser.nc) || "",
        usuarioNombre: (info && info.dataset.nombre) || (offUser && offUser.nombre) || "",
        errores: JSON.stringify(errores),
      };
      $("repEnviar").disabled = true; $("repMsg").textContent = "Enviando…";
      const guardarParaDespues = async () => {
        try { await window.Compostaje.colaReportes.agregar({ idLocal: campos.idLocal, campos, imagen }); return true; }
        catch (e) { return false; }
      };
      try {
        if (!navigator.onLine) throw new Error("sin red");
        const fd = new FormData();
        Object.entries(campos).forEach(([k, v]) => fd.append(k, v));
        if (imagen) fd.append("imagen", imagen, "captura.jpg");
        const r = await fetch("/reportar_problema", { method: "POST", body: fd, credentials: "same-origin" });
        if (!r.ok) throw new Error("servidor");
        $("repMsg").textContent = "✅ ¡Gracias! Tu reporte fue enviado.";
        setTimeout(cerrar, 1800);
      } catch (e) {
        if (await guardarParaDespues()) {
          $("repMsg").textContent = "📴 No se pudo enviar ahora. El reporte quedó guardado y se enviará solo cuando haya conexión.";
          setTimeout(cerrar, 2800);
        } else $("repMsg").textContent = "❌ No se pudo enviar el reporte. Intenta de nuevo.";
      } finally { $("repEnviar").disabled = false; }
    };
  });
})();