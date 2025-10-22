import os
import firebase_admin
from firebase_admin import credentials, firestore

BASE = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(BASE, "serviceAccountKey.json")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)

db = firestore.client()
reply_ref = db.collection("reply")
reply_ref.add({"text": "Hello from test!", "created_at": firestore.SERVER_TIMESTAMP})
print("Done writing test reply")
