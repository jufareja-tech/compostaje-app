from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client["compostaje_db"]
usuarios = db["usuarios"]

# 1. Poner a TODOS los usuarios como "estudiante" por defecto
usuarios.update_many({}, {"$set": {"rol": "estudiante"}, "$unset": {"es_admin": ""}})

# 2. Asegurar que Juan Francisco sea Admin
usuarios.update_one({"nombre": "Juan Francisco Reyes Jasso"}, {"$set": {"rol": "admin"}})

# 3. Si tienes otros usuarios de prueba (ej. Alejandro Kirk), ponlos como admin si quieres
# usuarios.update_one({"nombre": "Alejandro Kirk"}, {"$set": {"rol": "admin"}})

print("✅ Todos los usuarios fueron actualizados a 'estudiante'.")
print("✅ Juan Francisco es ahora 'admin'.")