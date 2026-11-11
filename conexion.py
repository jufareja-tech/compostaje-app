from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

cliente = MongoClient(MONGO_URI)

db = cliente["compostaje_db"]

print("Conexión con MongoDB establecida correctamente")