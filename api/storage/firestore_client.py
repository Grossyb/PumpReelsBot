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


     def decrement_credits(self, group_id, amount) -> None:
        doc_ref = self.group_collection.document(group_id)

        def transaction_decrement(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                # Document does not exist; no action or create with zero credits if needed
                # Optional: transaction.set(ref, {"credits": 0})
                return

            current_credits = snapshot.get("credits", 0)
            new_credits = max(current_credits - amount, 0)
            transaction.update(ref, {"credits": new_credits})

        self.db.run_transaction(lambda t: transaction_decrement(t, doc_ref))
