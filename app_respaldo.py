from flask import (Flask, render_template, request, redirect, url_for, flash,
                   session, abort, Response, send_file)
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from bson.errors import InvalidId
from collections import defaultdict
from functools import wraps
import os
import re
import base64
import hashlib
import math
import uuid
import unicodedata

load_dotenv()

app = Flask(__name__)
app.config.update({
    "SECRET_KEY": os.getenv("SECRET_KEY", "clave_secreta_por_defecto"),
    "UPLOAD_FOLDER": "static/uploads",
    "MAX_CONTENT_LENGTH": 9 * 1024 * 1024,  # foto de hasta 8 MB + formulario
})
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(mongo_uri)
db = client["compostaje_db"]
usuarios = db["usuarios"]
compostas = db["compostas"]
muestras = db["muestras"]

INGREDIENTES_SUGERIDOS = [
    "Manzanas", "Peras", "Hojas", "Tortillas", "Jitomate",
    "Tunas", "Plátano", "Otros residuos orgánicos",
]
SEXOS = ["Masculino", "Femenino", "Otro"]
CARRERAS = [
    "Ing. Informática", "Ing. Gestión Empresarial", "Ing. Sistemas Automotrices", "Ing. Industrial", "Ing. Bioquímica",
    "Ing. Electromecánica",
]
ABREV_SEXO = {"Masculino": "H", "Femenino": "M", "Otro": "Otro"}
ESTADOS = ["Pendiente", "Aceptada", "Rechazada"]
EXTENSIONES = {"png", "jpg", "jpeg", "gif"}
MAX_OTROS = 15
SEMESTRES_CURSADOS = list(range(1, 13))
MAX_FOTO_BYTES = 8 * 1024 * 1024
SIN_FOTO = {"fotoBase64": 0}
FIRMAS_IMAGEN = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def periodo_de(fecha):
    if fecha.month <= 6:
        return f"Ene–Jun {fecha.year}"
    return f"Ago–Dic {fecha.year}"


def clave_periodo(periodo):
    m = re.match(r"(Ene–Jun|Ago–Dic) (\d{4})$", periodo or "")
    if not m:
        return (0, 0)
    return (int(m.group(2)), 0 if m.group(1).startswith("Ene") else 1)


def periodo_de_composta(c):
    return c.get("periodo") or periodo_de(c["fechaRegistro"])


def leer_semestre(valor):
    try:
        n = int(valor)
    except (ValueError, TypeError):
        return None
    return n if n in SEMESTRES_CURSADOS else None


def semestre_cursado_de(c, u):
    return c.get("semestreCursado") or (u or {}).get("semestre")


def tipo_imagen(datos):
    for firma, mime in FIRMAS_IMAGEN:
        if datos.startswith(firma):
            return mime
    return None


def campos_foto(datos, mime):
    return {
        "fotoBase64": base64.b64encode(datos).decode("ascii"),
        "fotoTipo": mime,
        "fotoBytes": len(datos),
        "fotoSha256": hashlib.sha256(datos).hexdigest(),
    }


def listar(filtro=None):
    return compostas.find(filtro or {}, SIN_FOTO)


def _crear_indices():
    try:
        usuarios.create_index("numeroControl", unique=True)
        compostas.create_index("codigo", unique=True, sparse=True)
        compostas.create_index("usuarioId")
    except Exception as e:
        print("Aviso al crear índices:", e)


_crear_indices()


def limpiar_lista(valores, maximo=MAX_OTROS):
    vistos, limpios = set(), []
    for v in valores:
        v = " ".join((v or "").split())[:60]
        if v and v.lower() not in vistos:
            vistos.add(v.lower())
            limpios.append(v)
    return limpios[:maximo]


def generar_codigo():
    return f"COMP-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def generar_codigo_muestra():
    return f"MUE-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def migrar_registros_antiguos():
    try:
        compostas.update_many(
            {"estado": {"$exists": False}},
            {"$set": {"estado": "Pendiente", "observaciones": "",
                      "ingredientesObservados": [],
                      "ingredientesNoVisibles": [],
                      "revisadoPor": None, "fechaRevision": None}})
        for c in compostas.find({"codigo": {"$exists": False}}, SIN_FOTO):
            compostas.update_one({"_id": c["_id"]}, {"$set": {"codigo": generar_codigo()}})
        for c in compostas.find({"periodo": {"$exists": False}}, SIN_FOTO):
            if c.get("fechaRegistro"):
                compostas.update_one({"_id": c["_id"]}, {"$set": {"periodo": periodo_de(c["fechaRegistro"])}})
        for c in compostas.find({"fotoBase64": {"$exists": False}}, SIN_FOTO):
            nombre = os.path.basename(c.get("fotografia") or "")
            ruta = os.path.join(app.config["UPLOAD_FOLDER"], nombre)
            if nombre and os.path.isfile(ruta) and os.path.getsize(ruta) <= MAX_FOTO_BYTES:
                with open(ruta, "rb") as fh:
                    datos = fh.read()
                mime = tipo_imagen(datos)
                if mime:
                    compostas.update_one({"_id": c["_id"]}, {"$set": campos_foto(datos, mime)})
    except Exception as e:
        print("Aviso al migrar registros antiguos:", e)


migrar_registros_antiguos()


@app.template_filter("ingredientes")
def ingredientes_de(c):
    lista = [i for i in c.get("ingredientes", []) if i != "Otro"]
    otro = c.get("otroIngrediente")
    if otro and otro not in lista:
        lista.append(otro)
    return lista


@app.template_filter("fecha")
def formato_fecha(d):
    return d.strftime("%d/%m/%Y %H:%M") if d else ""


def login_requerido(f):
    @wraps(f)
    def interno(*a, **k):
        if "usuario_id" not in session:
            flash("Debes iniciar sesión para ver esta página.", "error")
            return redirect(url_for("login"))
        return f(*a, **k)

    return interno


# --- SISTEMA DE ROLES ---
def rol_requerido(*roles_permitidos):
    def decorador(f):
        @wraps(f)
        def interno(*a, **k):
            if "usuario_id" not in session:
                flash("Debes iniciar sesión para ver esta página.", "error")
                return redirect(url_for("login"))
            if session.get("rol") not in roles_permitidos:
                flash("Acceso denegado. No tienes permisos para esta sección.", "error")
                return redirect(url_for("inicio"))
            return f(*a, **k)

        return interno

    return decorador


def normalizar(texto):
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn").lower()
def estudiantes_validos():
    # Filtra a cualquier que NO sea admin, validador o laboratorista
    return {k: u for k, u in mapa_usuarios().items()
            if u.get("rol") not in ["admin", "validador", "laboratorista"]}

def periodos_disponibles():
    ps = {periodo_de_composta(c) for c in compostas.find({}, {"periodo": 1, "fechaRegistro": 1}) if
          c.get("fechaRegistro")}
    ps.add(periodo_de(datetime.now()))
    return sorted(ps, key=clave_periodo, reverse=True)


def obtener_composta(id_texto, con_foto=False):
    try:
        return compostas.find_one({"_id": ObjectId(id_texto)}, None if con_foto else SIN_FOTO)
    except (InvalidId, TypeError):
        return None


def mapa_usuarios():
    return {str(u["_id"]): u for u in usuarios.find()}


def parsear_fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def calcular_puntos_dh(participaciones, kilos):
    if participaciones >= 10:
        return 5 if kilos >= 16 else 3
    elif 5 <= participaciones <= 9:
        return 3 if kilos >= 10 else 1
    elif 3 <= participaciones <= 4:
        return 1 if kilos >= 5 else 0
    else:
        return 0


def coincide_nombre(u, q):
    q = normalizar(q.strip())
    return (not q) or q in normalizar(u.get("nombre", "")) \
        or q in u.get("numeroControl", "").lower()


def compostas_para_reporte(estado, inicio=None, fin=None):
    filtro = {} if estado == "Todas" else {"estado": "Aceptada"}
    rango = {}
    if inicio:
        rango["$gte"] = inicio
    if fin:
        rango["$lt"] = fin + timedelta(days=1)
    if rango:
        filtro["fechaRegistro"] = rango
    lista = list(listar(filtro).sort("fechaRegistro", 1))
    for c in lista:
        c["periodo"] = periodo_de_composta(c)
    return lista


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        numeroControl = request.form.get("numeroControl", "").strip()
        nombre = request.form.get("nombre", "").strip()
        sexo = request.form.get("sexo", "").strip()
        password = request.form.get("password", "")
        rol = request.form.get("rol", "estudiante")

        carrera = request.form.get("carrera", "").strip()
        semestre = leer_semestre(request.form.get("semestre"))

        if rol not in ["estudiante", "laboratorista"]:
            rol = "estudiante"

        if not (numeroControl and nombre and password):
            flash("Completa todos los campos obligatorios.", "error")
            return redirect(url_for("registro"))

        if sexo not in SEXOS:
            flash("Selecciona una opción de sexo válida.", "error")
            return redirect(url_for("registro"))

        # Validaciones solo si es estudiante
        if rol == "estudiante":
            if carrera not in CARRERAS:
                flash("Selecciona una carrera válida.", "error")
                return redirect(url_for("registro"))
            if semestre is None:
                flash("Selecciona el semestre que cursas.", "error")
                return redirect(url_for("registro"))
        else:
            # Si es personal, no tiene carrera ni semestre
            carrera = "Personal"
            semestre = 0

        if usuarios.find_one({"numeroControl": numeroControl}):
            flash("El número de control ya está registrado.", "error")
            return redirect(url_for("registro"))

        usuarios.insert_one({
            "numeroControl": numeroControl,
            "nombre": nombre,
            "sexo": sexo,
            "carrera": carrera,
            "semestre": semestre,
            "password": generate_password_hash(password),
            "rol": rol  # <-- SE GUARDA EL ROL DIRECTAMENTE
        })

        flash("Registro exitoso. Ahora puedes iniciar sesión.", "success")
        return redirect(url_for("login"))

    return render_template("registro.html", sexos=SEXOS,
                           semestres=SEMESTRES_CURSADOS,
                           carreras=CARRERAS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        numeroControl = request.form.get("numeroControl", "").strip()
        password = request.form.get("password", "")
        usuario = usuarios.find_one({"numeroControl": numeroControl})

        if usuario and check_password_hash(usuario["password"], password):
            if usuario and check_password_hash(usuario["password"], password):
                session["usuario_id"] = str(usuario["_id"])
                session["nombre"] = usuario["nombre"]
                # Esto asegura que si el rol está vacío, se le asigne estudiante
                rol_db = usuario.get("rol")
                session["rol"] = rol_db if rol_db else "estudiante"
                flash("Inicio de sesión exitoso.", "success")
                return redirect(url_for("inicio"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/perfil", methods=["GET", "POST"])
@rol_requerido("estudiante")
def perfil():
    usuario = usuarios.find_one({"_id": ObjectId(session["usuario_id"])})

    if request.method == "POST":
        semestre = leer_semestre(request.form.get("semestre"))
        if semestre is None:
            flash("Selecciona un semestre válido.", "error")
            return redirect(url_for("perfil"))
        usuarios.update_one({"_id": usuario["_id"]}, {"$set": {"semestre": semestre}})
        flash("Semestre actualizado.", "success")
        return redirect(url_for("inicio"))

    periodo_actual = periodo_de(datetime.now())
    lista_aceptadas = list(compostas.find({
        "usuarioId": session["usuario_id"],
        "estado": "Aceptada",
        "periodo": periodo_actual
    }))

    total_participaciones = len(lista_aceptadas)
    total_kilos = sum(c["pesoKg"] for c in lista_aceptadas)
    puntos = calcular_puntos_dh(total_participaciones, total_kilos)

    color_clase = "bg-rojo"
    if puntos == 1:
        color_clase = "bg-naranja"
    elif puntos == 3:
        color_clase = "bg-verde-claro"
    elif puntos == 5:
        color_clase = "bg-verde-oscuro"
        if total_kilos > 16:
            color_clase = "bg-azul"

    return render_template("perfil.html", u=usuario, semestres=SEMESTRES_CURSADOS,
                           periodo=periodo_actual, participaciones=total_participaciones,
                           kilos=round(total_kilos, 2), puntos=puntos, color_clase=color_clase)


@app.route("/registrar_composta", methods=["GET", "POST"])
@rol_requerido("estudiante")
def registrar_composta():
    usuario = usuarios.find_one({"_id": ObjectId(session["usuario_id"])})
    if not usuario or not usuario.get("semestre"):
        flash("Antes de registrar una composta indica el semestre que cursas.", "info")
        return redirect(url_for("perfil"))

    if request.method == "POST":
        peso = request.form.get("peso", "").strip()
        foto = request.files.get("fotografia") or request.files.get("fotografiaCamara")
        seleccion = request.form.getlist("ingredientes")
        otros = limpiar_lista(request.form.getlist("otrosIngredientes"))

        def error(msg):
            flash(msg, "error")
            return redirect(url_for("registrar_composta"))

        if not foto or not foto.filename:
            return error("Debes seleccionar una fotografía.")
        datos = foto.read()
        if len(datos) > MAX_FOTO_BYTES:
            return error("La fotografía pesa más de 8 MB.")
        mime = tipo_imagen(datos)
        if not mime:
            return error("La imagen no es válida. Usa JPG, PNG o GIF.")
        nombre_original = secure_filename(foto.filename) or "foto"

        try:
            peso_float = float(peso)
            if not math.isfinite(peso_float) or peso_float <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return error("El peso debe ser un número mayor que cero.")

        permitidos = set(INGREDIENTES_SUGERIDOS) | {"Otro"}
        if any(i not in permitidos for i in seleccion):
            return error("Hay ingredientes no válidos.")
        ingredientes = [i for i in seleccion if i != "Otro"]
        if "Otro" in seleccion:
            ingredientes += [o for o in otros if o.lower() not in {x.lower() for x in ingredientes}]
        if not ingredientes:
            return error("Selecciona al menos un ingrediente.")

        ahora = datetime.now()
        compostas.insert_one({
            "codigo": generar_codigo(),
            "usuarioId": session["usuario_id"],
            "fotografia": nombre_original,
            **campos_foto(datos, mime),
            "semestreCursado": usuario["semestre"],
            "pesoKg": peso_float,
            "fechaRegistro": ahora,
            "periodo": periodo_de(ahora),
            "ingredientes": ingredientes,
            "estado": "Pendiente",
            "observaciones": "",
        })
        flash("¡Composta registrada! Quedó pendiente de revisión.", "success")
        return redirect(url_for("mis_compostas"))

    return render_template("Registrar_composta.html", sugeridos=INGREDIENTES_SUGERIDOS)


@app.route("/mis_compostas")
@rol_requerido("estudiante")
def mis_compostas():
    lista = list(listar({"usuarioId": session["usuario_id"]}).sort("fechaRegistro", DESCENDING))
    for c in lista:
        c["periodo"] = periodo_de_composta(c)
    total = sum(c["pesoKg"] for c in lista if c.get("estado") == "Aceptada")
    return render_template("mis_compostas.html", compostas=lista, kilos_aceptados=round(total, 2))


@app.route("/foto/<id_composta>")
@login_requerido
def foto(id_composta):
    c = obtener_composta(id_composta, con_foto=True)
    if not c or not (
            session.get("rol") in ["admin", "validador", "laboratorista"] or c["usuarioId"] == session["usuario_id"]):
        abort(404)
    if c.get("fotoBase64"):
        datos, mime = base64.b64decode(c["fotoBase64"]), c.get("fotoTipo")
    else:
        ruta = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(c.get("fotografia") or ""))
        if not os.path.isfile(ruta):
            abort(404)
        with open(ruta, "rb") as fh:
            datos = fh.read()
        mime = tipo_imagen(datos)
    if not mime:
        abort(404)
    resp = Response(datos, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.errorhandler(413)
def foto_muy_grande(_e):
    flash("La fotografía pesa más de 8 MB.", "error")
    return redirect(url_for("registrar_composta"))


@app.route("/corregir_composta/<id_composta>", methods=["GET", "POST"])
@rol_requerido("estudiante")
def corregir_composta(id_composta):
    c = obtener_composta(id_composta, con_foto=True)

    if not c or c["usuarioId"] != session["usuario_id"] or c.get("estado") != "Rechazada":
        flash("No puedes editar esta composta.", "error")
        return redirect(url_for("mis_compostas"))

    if request.method == "POST":
        peso = request.form.get("peso", "").strip()
        foto = request.files.get("fotografia")
        seleccion = request.form.getlist("ingredientes")
        otros = limpiar_lista(request.form.getlist("otrosIngredientes"))

        def error(msg):
            flash(msg, "error")
            return redirect(url_for("corregir_composta", id_composta=id_composta))

        try:
            peso_float = float(peso)
            if peso_float <= 0: raise ValueError
        except:
            return error("Peso inválido.")

        ingredientes = [i for i in seleccion if i != "Otro"]
        if "Otro" in seleccion:
            ingredientes += [o for o in otros if o.lower() not in {x.lower() for x in ingredientes}]
        if not ingredientes:
            return error("Selecciona ingredientes.")

        cambios = {
            "pesoKg": peso_float,
            "ingredientes": ingredientes,
            "estado": "Pendiente",
            "observaciones": "",
        }

        if foto and foto.filename:
            datos = foto.read()
            mime = tipo_imagen(datos)
            if len(datos) > MAX_FOTO_BYTES or not mime:
                return error("Foto inválida.")
            cambios["fotografia"] = secure_filename(foto.filename) or "foto"
            cambios.update(campos_foto(datos, mime))

        compostas.update_one({"_id": c["_id"]}, {"$set": cambios})
        flash("¡Composta corregida y reenviada!", "success")
        return redirect(url_for("mis_compostas"))

    declarados = ingredientes_de(c)
    return render_template("corregir_composta.html", c=c, declarados=declarados, sugeridos=INGREDIENTES_SUGERIDOS)


@app.route("/admin")
@rol_requerido("admin", "validador")
def admin():
    estado = request.args.get("estado", "Pendiente")
    filtro = {} if estado == "Todas" else {"estado": estado}
    if estado not in ESTADOS + ["Todas"]:
        estado, filtro = "Pendiente", {"estado": "Pendiente"}

    alumnos = mapa_usuarios()
    lista = []
    for c in listar(filtro).sort("fechaRegistro", DESCENDING):
        u = alumnos.get(c["usuarioId"])
        c["nombreAlumno"] = u["nombre"] if u else "Usuario eliminado"
        c["numeroControl"] = u.get("numeroControl", "N/A") if u else "N/A"
        lista.append(c)

    cuenta = {e: compostas.count_documents({"estado": e}) for e in ESTADOS}
    kilos_aceptados = sum(c["pesoKg"] for c in listar({"estado": "Aceptada"}))
    return render_template(
        "admin.html", compostas=lista, estado=estado, estados=ESTADOS,
        cuenta=cuenta, total_usuarios=usuarios.count_documents({"rol": "estudiante"}),
        total_compostas=compostas.count_documents({}), total_kilos=round(kilos_aceptados, 2))


@app.route("/admin/revisar/<id_composta>", methods=["GET", "POST"])
@rol_requerido("admin", "validador")
def revisar(id_composta):
    c = obtener_composta(id_composta)
    if not c:
        flash("La composta no existe.", "error")
        return redirect(url_for("admin"))
    declarados = ingredientes_de(c)

    if request.method == "POST":
        decision = request.form.get("decision")
        observaciones = request.form.get("observaciones", "").strip()[:500]

        if decision not in ("Aceptada", "Rechazada"):
            flash("Elige una decisión.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))
        if decision == "Rechazada" and not observaciones:
            flash("Escribe el motivo.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))

        compostas.update_one({"_id": c["_id"]}, {"$set": {
            "estado": decision,
            "observaciones": observaciones,
            "revisadoPor": session["usuario_id"],
            "fechaRevision": datetime.now()
        }})
        flash(f"Composta {decision}.", "success")
        return redirect(url_for("admin"))

    u = usuarios.find_one({"_id": ObjectId(c["usuarioId"])}) if ObjectId.is_valid(c["usuarioId"]) else None
    return render_template("admin_revisar.html", c=c, alumno=u, declarados=declarados, sugeridos=INGREDIENTES_SUGERIDOS)


@app.route("/admin/estudiantes")
@rol_requerido("admin","validador")
def estudiantes():
    q = request.args.get("q", "").strip()
    periodo = request.args.get("periodo", "")
    sem = leer_semestre(request.args.get("sem"))
    solo = request.args.get("solo") == "1"
    periodos = periodos_disponibles()
    if periodo not in periodos: periodo = ""

    stats = defaultdict(lambda: {"reg": 0, "acep": 0, "kilos": 0.0})
    for c in listar():
        if periodo and periodo_de_composta(c) != periodo: continue
        s = stats[c["usuarioId"]]
        s["reg"] += 1
        if c.get("estado") == "Aceptada":
            s["acep"] += 1
            s["kilos"] += c["pesoKg"]

    filas = []
    for uid, u in estudiantes_validos().items():
        if not coincide_nombre(u, q) or (sem and u.get("semestre") != sem): continue
        s = stats.get(uid, {"reg": 0, "acep": 0, "kilos": 0.0})
        if solo and not s["reg"]: continue
        filas.append({"id": uid, "u": u, "reg": s["reg"], "acep": s["acep"], "kilos": round(s["kilos"], 2)})
    filas.sort(key=lambda f: normalizar(f["u"]["nombre"]))

    return render_template("estudiantes.html", filas=filas, q=q, periodo=periodo, periodos=periodos, solo=solo,
                           sem=sem or "", semestres=SEMESTRES_CURSADOS)


@app.route("/admin/estudiantes/<uid>")
@rol_requerido("admin","validador")
def estudiante_detalle(uid):
    u = estudiantes_validos().get(uid)
    if not u:
        flash("El estudiante no existe.", "error")
        return redirect(url_for("estudiantes"))
    lista = list(listar({"usuarioId": uid}).sort("fechaRegistro", DESCENDING))
    por_periodo = defaultdict(lambda: {"reg": 0, "acep": 0, "kilos": 0.0})
    for c in lista:
        c["periodo"] = periodo_de_composta(c)
        c["semcurs"] = semestre_cursado_de(c, u)
        r = por_periodo[c["periodo"]]
        r["reg"] += 1
        if c.get("estado") == "Aceptada":
            r["acep"] += 1
            r["kilos"] += c["pesoKg"]
    resumen = [{"periodo": p, "reg": v["reg"], "acep": v["acep"], "kilos": round(v["kilos"], 2)} for p, v in
               sorted(por_periodo.items(), key=lambda x: clave_periodo(x[0]), reverse=True)]

    total_aceptadas = sum(r["acep"] for r in resumen)
    total_kilos = sum(r["kilos"] for r in resumen)
    puntos_dh = calcular_puntos_dh(total_aceptadas, total_kilos)

    return render_template("estudiante_detalle.html", u=u, uid=uid, compostas=lista, resumen=resumen,
                           puntos_dh=puntos_dh)


@app.route("/admin/reportes")
@rol_requerido("admin","validador")
def reportes():
    reporte = request.args.get("reporte", "participaciones")
    estado = "Todas" if request.args.get("estado") == "Todas" else "Aceptada"
    alumnos = estudiantes_validos()
    carreras = sorted({u.get("carrera", "") for u in alumnos.values() if u.get("carrera")})
    periodos = periodos_disponibles()
    datos = {}
    inicio_txt = request.args.get("inicio", "")
    fin_txt = request.args.get("fin", "")
    carrera_sel = request.args.get("carrera", "")
    alumno_sel = request.args.get("alumno", "")
    q = request.args.get("q", "").strip()
    periodo_sel = request.args.get("periodo", "")
    sem_sel = leer_semestre(request.args.get("sem"))
    if periodo_sel not in periodos: periodo_sel = ""

    if reporte == "participaciones":
        filas = defaultdict(lambda: {"reg": 0, "acep": 0, "kilos": 0.0})
        for c in listar():
            u = alumnos.get(c["usuarioId"])
            per = periodo_de_composta(c)
            if not u or not coincide_nombre(u, q) or (periodo_sel and per != periodo_sel) or (
                    sem_sel and semestre_cursado_de(c, u) != sem_sel):
                continue
            f = filas[(per, c["usuarioId"], semestre_cursado_de(c, u))]
            f["reg"] += 1
            if c.get("estado") == "Aceptada":
                f["acep"] += 1
                f["kilos"] += c["pesoKg"]
        datos["filas"] = sorted(
            [{"periodo": per, "id": uid, "u": alumnos[uid], "sem": semc, "reg": v["reg"], "acep": v["acep"],
              "kilos": round(v["kilos"], 2), "puntos": calcular_puntos_dh(v["acep"], round(v["kilos"], 2))} for
             (per, uid, semc), v in filas.items()],
            key=lambda f: (tuple(-x for x in clave_periodo(f["periodo"])), normalizar(f["u"]["nombre"])))

    elif reporte == "estudiante":
        datos["alumnos"] = sorted(alumnos.values(), key=lambda u: u["nombre"])
        if alumno_sel in alumnos:
            u = alumnos[alumno_sel]
            lista = [c for c in compostas_para_reporte(estado) if c["usuarioId"] == alumno_sel]
            acumulado = 0.0
            for c in lista:
                acumulado += c["pesoKg"]
                c["acumulado"] = round(acumulado, 2)
            puntos_alumno = calcular_puntos_dh(len(lista), round(acumulado, 2))
            datos.update(alumno=u, lista=lista, total=round(acumulado, 2), puntos=puntos_alumno)

    return render_template("reportes.html", reporte=reporte, estado=estado, datos=datos, carreras=carreras,
                           inicio=inicio_txt, fin=fin_txt, carrera_sel=carrera_sel, alumno_sel=alumno_sel, q=q,
                           periodos=periodos, periodo_sel=periodo_sel, sem_sel=sem_sel or "",
                           semestres=SEMESTRES_CURSADOS)


@app.route("/laboratorio")
@rol_requerido("admin", "laboratorista")
def laboratorio():
    lista = list(muestras.find().sort("fecha", DESCENDING))
    return render_template("laboratorio.html", muestras=lista)


@app.route("/laboratorio/registrar", methods=["GET", "POST"])
@rol_requerido("admin", "laboratorista")
def registrar_muestra():
    if request.method == "POST":
        tipo_residuo = request.form.get("tipo_residuo", "").strip()
        ph = request.form.get("ph", "").strip()
        humedad = request.form.get("humedad", "").strip()
        temperatura = request.form.get("temperatura", "").strip()
        observaciones = request.form.get("observaciones", "").strip()
        foto = request.files.get("fotografia")

        def error(msg):
            flash(msg, "error")
            return redirect(url_for("registrar_muestra"))

        if not tipo_residuo: return error("Escribe el tipo de residuo.")

        try:
            ph_float = float(ph) if ph else None
            humedad_float = float(humedad) if humedad else None
            temp_float = float(temperatura) if temperatura else None
        except ValueError:
            return error("Las mediciones deben ser números válidos.")

        foto_campos = {}
        nombre_foto = ""
        if foto and foto.filename:
            datos = foto.read()
            if len(datos) > MAX_FOTO_BYTES: return error("La fotografía pesa más de 8 MB.")
            mime = tipo_imagen(datos)
            if not mime: return error("La imagen no es válida.")
            nombre_foto = secure_filename(foto.filename) or "muestra"
            foto_campos = campos_foto(datos, mime)

        muestras.insert_one({
            "codigo": generar_codigo_muestra(), "tipo_residuo": tipo_residuo, "ph": ph_float,
            "humedad": humedad_float, "temperatura": temp_float, "observaciones": observaciones,
            "fecha": datetime.now(), "laboratorista": session.get("nombre"),
            "fotografia": nombre_foto, **foto_campos
        })

        flash("¡Muestra registrada exitosamente!", "success")
        return redirect(url_for("laboratorio"))

    return render_template("laboratorio_registrar.html")


@app.route("/muestra_foto/<id_muestra>")
@rol_requerido("admin", "laboratorista")
def muestra_foto(id_muestra):
    try:
        m = muestras.find_one({"_id": ObjectId(id_muestra)})
    except (InvalidId, TypeError):
        abort(404)
    if not m or not m.get("fotoBase64"): abort(404)
    datos = base64.b64decode(m["fotoBase64"])
    mime = m.get("fotoTipo", "image/jpeg")
    resp = Response(datos, mimetype=mime)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)