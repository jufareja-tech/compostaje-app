"""Convierte a un usuario ya registrado en administrador.

Uso (con el proyecto detenido o en otra terminal de PyCharm):
    python make_admin.py NUMERO_DE_CONTROL
Para quitar el permiso:
    python make_admin.py NUMERO_DE_CONTROL --quitar
"""
import sys
from conexion import db

if len(sys.argv) < 2:
    sys.exit(__doc__)

numero = sys.argv[1].strip()
valor = "--quitar" not in sys.argv
r = db["usuarios"].update_one({"numeroControl": numero},
                              {"$set": {"es_admin": valor}})
if r.matched_count == 0:
    sys.exit(f"No existe ningún usuario con número de control {numero}. "
             "Primero regístralo en la página.")
print(f"Usuario {numero}: administrador = {valor}")
