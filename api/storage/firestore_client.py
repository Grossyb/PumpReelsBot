from firebase_admin import credentials, firestore, storage, initialize_app
from pandas import to_datetime, Timestamp
import firebase_admin


class FirestoreClient:
    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.Certificate('/secrets/pumpreels/pumpreels_service_key.json')
            initialize_app(cred)

        # self.bucket = storage.bucket()

        self.db = firestore.client()
        self.group_collection = self.db.collection('groups')


    def create_group(self, data):
        group_id = str(data['id'])

        doc_ref = self.group_collection.document(group_id)
        doc_ref.set({
            "title": data['title'],
            "type": data['type'],
            "credits": 0,
            "created_at": Timestamp.now()
        })

        return doc_ref.id


    def get_group(self, group_id):
        doc_ref = self.group_collection.document(group_id)
        doc = doc_ref.get()

        if doc.exists:
            return doc.to_dict()

        return None
