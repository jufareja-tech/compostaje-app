from pymongo import MongoClient

# Conexión directa a tu MongoDB local
client = MongoClient("mongodb://localhost:27017/")
db = client["compostaje_db"]
usuarios = db["usuarios"]

# 1. Convertir a los antiguos admin al nuevo sistema
usuarios.update_many({"es_admin": True}, {"$set": {"rol": "admin"}, "$unset": {"es_admin": ""}})

# 2. A los que no tienen rol, ponerles "estudiante"
usuarios.update_many({"rol": {"$exists": False}}, {"$set": {"rol": "estudiante"}})

# 3. Asegurarnos de que Juan Francisco sea Admin (por si las dudas)
usuarios.update_one({"nombre": "Juan Francisco Reyes Jasso"}, {"$set": {"rol": "admin"}})

print("✅ Base de datos actualizada correctamente.")