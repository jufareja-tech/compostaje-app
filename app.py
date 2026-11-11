from flask import (Flask, render_template, request, redirect, url_for, flash, session, abort, Response, send_from_directory)
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from bson.errors import InvalidId
from collections import defaultdict
from functools import wraps
from pymongo.errors import PyMongoError
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
    "MAX_CONTENT_LENGTH": 20 * 1024 * 1024,  # Aumentado a 20 MB por las múltiples fotos
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
    except (PyMongoError, OSError) as e:  # <-- CAMBIO AQUÍ
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

def resumir_sexo(grupo):
    por_sexo = defaultdict(set)
    for uid, sexo in grupo:
        por_sexo[sexo].add(uid)
    partes = [f"{len(por_sexo[s])} {ABREV_SEXO.get(s, s)}"
              for s in SEXOS if s in por_sexo]
    otros = [s for s in por_sexo if s not in SEXOS]
    partes += [f"{len(por_sexo[s])} {s}" for s in otros]
    return " · ".join(partes) or "—"


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
        # SEGURIDAD: Si alguien intenta enviar "admin" o "validador" por consola, lo forzamos a estudiante
        if rol not in ["estudiante", "laboratorista"]:
            rol = "estudiante"

        carrera = request.form.get("carrera", "").strip()
        semestre = leer_semestre(request.form.get("semestre"))

        if not (numeroControl and nombre and password):
            flash("Completa todos los campos obligatorios.", "error")
            return redirect(url_for("registro"))

        if sexo not in SEXOS:
            flash("Selecciona una opción de sexo válida.", "error")
            return redirect(url_for("registro"))

        if rol == "estudiante":
            if carrera not in CARRERAS:
                flash("Selecciona una carrera válida.", "error")
                return redirect(url_for("registro"))
            if semestre is None:
                flash("Selecciona el semestre que cursas.", "error")
                return redirect(url_for("registro"))
        else:
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
            "rol": rol
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
            session["usuario_id"] = str(usuario["_id"])
            session["nombre"] = usuario["nombre"]
            rol_db = usuario.get("rol")
            session["rol"] = rol_db if rol_db else "estudiante"
            session["numeroControl"] = numeroControl
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

    todas_aceptadas = list(compostas.find({"usuarioId": session["usuario_id"], "estado": "Aceptada"}))
    historial_dict = defaultdict(lambda: {"part": 0, "kilos": 0.0})
    for c in todas_aceptadas:
        per = periodo_de_composta(c)
        historial_dict[per]["part"] += 1
        historial_dict[per]["kilos"] += c["pesoKg"]

    historial = []
    for per, stats in historial_dict.items():
        pts = calcular_puntos_dh(stats["part"], stats["kilos"])
        historial.append({
            "periodo": per,
            "participaciones": stats["part"],
            "kilos": round(stats["kilos"], 2),
            "puntos": pts
        })
    historial.sort(key=lambda x: clave_periodo(x["periodo"]), reverse=True)

    return render_template("perfil.html", u=usuario, semestres=SEMESTRES_CURSADOS,
                           periodo=periodo_actual, participaciones=total_participaciones,
                           kilos=round(total_kilos, 2), puntos=puntos, color_clase=color_clase,
                           historial=historial)


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
        peso_form = request.form.get("peso")
        marcados = request.form.getlist("declarados")
        otros_declarados = request.form.getlist("otrosDeclarados")
        ingredientes_finales = limpiar_lista(marcados + otros_declarados, maximo=30)

        if decision not in ("Aceptada", "Rechazada"):
            flash("Elige una decisión.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))
        if decision == "Rechazada" and not observaciones:
            flash("Escribe el motivo.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))

        try:
            peso_float = float(peso_form)
            if peso_float <= 0: raise ValueError
        except (ValueError, TypeError):
            flash("El peso debe ser un número válido mayor a 0.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))

        if not ingredientes_finales:
            flash("Debe haber al menos un ingrediente seleccionado.", "error")
            return redirect(url_for("revisar", id_composta=id_composta))

        compostas.update_one({"_id": c["_id"]}, {"$set": {
            "estado": decision,
            "observaciones": observaciones,
            "pesoKg": peso_float,
            "ingredientes": ingredientes_finales,
            "revisadoPor": session["usuario_id"],
            "fechaRevision": datetime.now()
        }})
        flash(f"Composta {decision}. Datos guardados correctamente.", "success")
        return redirect(url_for("admin"))

    u = usuarios.find_one({"_id": ObjectId(c["usuarioId"])}) if ObjectId.is_valid(c["usuarioId"]) else None
    return render_template("admin_revisar.html", c=c, alumno=u, declarados=declarados, sugeridos=INGREDIENTES_SUGERIDOS)


@app.route("/admin/estudiantes")
@rol_requerido("admin", "validador")
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
@rol_requerido("admin", "validador")
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
@rol_requerido("admin", "validador")
def reportes():
    reporte = request.args.get("reporte", "participaciones")
    estado = "Todas" if request.args.get("estado") == "Todas" else "Aceptada"
    alumnos = estudiantes_validos()
    carreras = sorted(
        {u.get("carrera", "") for u in alumnos.values() if u.get("carrera") and u.get("carrera") != "Personal"})

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

    elif reporte == "periodo":
        ini, fin = parsear_fecha(inicio_txt), parsear_fecha(fin_txt)
        if ini and fin and ini > fin:
            flash("La fecha inicial no puede ser posterior a la final.", "error")
        else:
            filas = defaultdict(lambda: {"kilos": 0.0, "n": 0, "g": []})
            for c in compostas_para_reporte(estado, ini, fin):
                u = alumnos.get(c["usuarioId"])
                # --- CAMBIO 2: Solo revisar que el usuario exista ---
                if not u or (carrera_sel and u.get("carrera") != carrera_sel):
                    continue

                f = filas[u.get("carrera", "Sin carrera")]
                f["kilos"] += c["pesoKg"]
                f["n"] += 1
                f["g"].append((c["usuarioId"], u.get("sexo", "")))
            datos["filas"] = [
                {"carrera": k, "entregas": v["n"], "kilos": round(v["kilos"], 2),
                 "sexo": resumir_sexo(v["g"])}
                for k, v in sorted(filas.items())]
            datos["total"] = round(sum(f["kilos"] for f in datos["filas"]), 2)

    elif reporte == "semestre":
        filas = defaultdict(lambda: {"kilos": 0.0, "n": 0, "g": set()})
        for c in compostas_para_reporte(estado):
            f = filas[c["periodo"]]
            f["kilos"] += c["pesoKg"]
            f["n"] += 1
            f["g"].add(c["usuarioId"])
        datos["filas"] = [{"periodo": p, "entregas": v["n"],
                           "participantes": len(v["g"]),
                           "kilos": round(v["kilos"], 2)}
                          for p, v in sorted(filas.items(),
                                             key=lambda x: clave_periodo(x[0]),
                                             reverse=True)]

    elif reporte == "semestre_sexo_carrera":
        filas = defaultdict(lambda: {"kilos": 0.0, "g": []})
        for c in compostas_para_reporte(estado):
            u = alumnos.get(c["usuarioId"])
            if not u:
                continue
            llave = (c["periodo"], u.get("carrera", "Sin carrera"))
            filas[llave]["kilos"] += c["pesoKg"]
            filas[llave]["g"].append((c["usuarioId"], u.get("sexo", "")))
        datos["filas"] = [
            {"periodo": p, "carrera": ca, "kilos": round(v["kilos"], 2),
             "participantes": len({g[0] for g in v["g"]}),
             "sexo": resumir_sexo(v["g"])}
            for (p, ca), v in sorted(
                filas.items(),
                key=lambda x: (tuple(-n for n in clave_periodo(x[0][0])), x[0][1]))]

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

    #Calcular Estadísticas Globales
    todas_aceptadas = list(compostas.find({"estado": "Aceptada"}))
    total_kilos_global = sum(c["pesoKg"] for c in todas_aceptadas)
    total_participaciones_global = len(todas_aceptadas)
    estudiantes_participantes = len({c["usuarioId"] for c in todas_aceptadas})
    promedio_kilos = 0
    if estudiantes_participantes > 0:
        promedio_kilos = total_kilos_global / estudiantes_participantes

    datos["stats_globales"] = {
        "kilos": round(total_kilos_global, 2),
        "participaciones": total_participaciones_global,
        "estudiantes": estudiantes_participantes,
        "promedio": round(promedio_kilos, 2)
    }
    return render_template("reportes.html", reporte=reporte, estado=estado, datos=datos, carreras=carreras,
                           inicio=inicio_txt, fin=fin_txt, carrera_sel=carrera_sel, alumno_sel=alumno_sel, q=q,
                           periodos=periodos, periodo_sel=periodo_sel, sem_sel=sem_sel or "",
                           semestres=SEMESTRES_CURSADOS)


@app.route("/laboratorio")
@rol_requerido("admin", "laboratorista")
def laboratorio():
    q = request.args.get("q", "").strip()
    filtro = {}
    if q:
        filtro = {"$or": [
            {"tipo_residuo": {"$regex": q, "$options": "i"}},
            {"codigo": {"$regex": q, "$options": "i"}}
        ]}
    lista = list(muestras.find(filtro).sort("fecha", DESCENDING))
    return render_template("laboratorio.html", muestras=lista)


@app.route("/laboratorio/registrar", methods=["GET", "POST"])
@rol_requerido("admin", "laboratorista")
def registrar_muestra():
    if request.method == "POST":
        # Capturamos todos los campos del formulario
        tipo_residuo = request.form.get("tipo_residuo", "").strip()
        inoculo = request.form.get("inoculo", "").strip()
        fecha_muestreo = request.form.get("fecha_muestreo", "").strip()
        fecha_inoculacion = request.form.get("fecha_inoculacion", "").strip()
        temp_ambiente = request.form.get("temp_ambiente", "").strip()
        temp_pila = request.form.get("temp_pila", "").strip()

        # Mediciones con su desviación estándar
        ph = request.form.get("ph", "").strip()
        ph_desv = request.form.get("ph_desv", "").strip()
        conductividad = request.form.get("conductividad", "").strip()
        conductividad_desv = request.form.get("conductividad_desv", "").strip()
        humedad = request.form.get("humedad", "").strip()
        humedad_desv = request.form.get("humedad_desv", "").strip()
        materia_organica = request.form.get("materia_organica", "").strip()
        materia_organica_desv = request.form.get("materia_organica_desv", "").strip()
        cenizas = request.form.get("cenizas", "").strip()
        cenizas_desv = request.form.get("cenizas_desv", "").strip()
        carbono = request.form.get("carbono", "").strip()
        carbono_desv = request.form.get("carbono_desv", "").strip()
        nitrogeno = request.form.get("nitrogeno", "").strip()
        relacion_cn = request.form.get("relacion_cn", "").strip()

        observaciones = request.form.get("observaciones", "").strip()
        fotos = request.files.getlist("fotografias")

        def error(msg):
            flash(msg, "error")
            return redirect(url_for("registrar_muestra"))

        if not tipo_residuo: return error("Escribe el tipo de residuo.")

        # Función auxiliar para convertir a float o None
        def to_float(val):
            try:
                return float(val) if val else None
            except ValueError:
                return None

        fotos_guardadas = []
        for foto in fotos:
            if foto and foto.filename:
                datos = foto.read()
                if len(datos) > MAX_FOTO_BYTES: return error("Una fotografía pesa más de 8 MB.")
                mime = tipo_imagen(datos)
                if not mime: return error("Una imagen no es válida.")
                fotos_guardadas.append({
                    "nombre": secure_filename(foto.filename) or "muestra",
                    **campos_foto(datos, mime)
                })

        # Guardamos en MongoDB
        muestras.insert_one({
            "codigo": generar_codigo_muestra(),
            "tipo_residuo": tipo_residuo,
            "inoculo": inoculo,
            "fecha_muestreo": fecha_muestreo,
            "fecha_inoculacion": fecha_inoculacion,
            "temp_ambiente": to_float(temp_ambiente),
            "temp_pila": to_float(temp_pila),
            "ph": to_float(ph),
            "ph_desv": to_float(ph_desv),
            "conductividad": to_float(conductividad),
            "conductividad_desv": to_float(conductividad_desv),
            "humedad": to_float(humedad),
            "humedad_desv": to_float(humedad_desv),
            "materia_organica": to_float(materia_organica),
            "materia_organica_desv": to_float(materia_organica_desv),
            "cenizas": to_float(cenizas),
            "cenizas_desv": to_float(cenizas_desv),
            "carbono": to_float(carbono),
            "carbono_desv": to_float(carbono_desv),
            "nitrogeno": to_float(nitrogeno),
            "relacion_cn": relacion_cn,
            "observaciones": observaciones,
            "fecha": datetime.now(),
            "laboratorista": session.get("nombre"),
            "fotografias": fotos_guardadas
        })


        flash("¡Muestra registrada exitosamente!", "success")
        return redirect(url_for("laboratorio"))

    return render_template("laboratorio_registrar.html")

@app.route('/sw.js')
def sw():
    return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')


@app.route("/sync_offline_composta", methods=["POST"])
@rol_requerido("estudiante")
def sync_offline_composta():
    data = request.get_json()
    if not data:
        return {"error": "No data"}, 400

    # Extraer datos
    peso = data.get("peso")
    ingredientes = data.get("ingredientes", [])
    foto_base64 = data.get("fotoBase64")

    usuario = usuarios.find_one({"_id": ObjectId(session["usuario_id"])})
    if not usuario:
        return {"error": "Usuario no encontrado"}, 404

    # Preparar los campos de la foto de forma segura
    foto_campos = {}
    if foto_base64:
        try:
            header, encoded = foto_base64.split(",", 1)
            mime = header.split(";")[0].split(":")[1]
            datos_binarios = base64.b64decode(encoded)
            foto_campos = campos_foto(datos_binarios, mime)
        except Exception as e:
            print("Error al procesar la foto offline:", e)

    ahora = datetime.now()

    # Guardar en MongoDB
    compostas.insert_one({
        "codigo": generar_codigo(),
        "usuarioId": session["usuario_id"],
        "fotografia": data.get("fotoNombre", "offline.jpg"),
        **foto_campos,
        "semestreCursado": usuario.get("semestre", 1),
        "pesoKg": float(peso),
        "fechaRegistro": ahora,
        "periodo": periodo_de(ahora),
        "ingredientes": ingredientes,
        "estado": "Pendiente",
        "observaciones": "",
    })

    return {"success": True}, 200

if __name__ == "__main__":
    # El host '0.0.0.0' permite conexiones desde otros dispositivos en la misma red
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)



    # mongodb+srv://<db_username>:<db_password>@cluster0.i844bev.mongodb.net/


    #mongodb+srv://admin_composta:MiPasswordSeguro123@cluster0.i844bev.mongodb.net/
