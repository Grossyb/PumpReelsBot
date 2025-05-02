from firebase_admin import credentials, firestore, storage, initialize_app
from pandas import Timestamp
import firebase_admin


class FirestoreClient:
    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.Certificate('/secrets/pumpreels/pumpreels_service_key.json')
            initialize_app(cred)

        self.db = firestore.client()
        self.group_collection = self.db.collection('groups')

    def create_group(self, data, creator_user_id):
        group_id = str(data['id'])

        doc_ref = self.group_collection.document(group_id)
        doc_ref.set({
            "title": data['title'],
            "type": data['type'],
            "creator_id": creator_user_id,
            "credits": 0,
            "created_at": Timestamp.now()
        })

        return doc_ref.id

    def get_group(self, group_id):
        doc_ref = self.group_collection.document(group_id)
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            data['group_id'] = doc.id
            return data

        return None

    def get_groups_by_creator(self, creator_id):
        query = self.group_collection.where("creator_id", "==", creator_id)
        docs = query.stream()
        results = []

        for doc in docs:
            data = doc.to_dict()
            data['group_id'] = doc.id
            results.append(data)

        return results

    def add_credits(self, group_id, amount):
        doc_ref = self.group_collection.document(group_id)

        @firestore.transactional
        def transaction_add(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                transaction.set(doc_ref, {
                    "credits": amount,
                    "created_at": firestore.SERVER_TIMESTAMP
                })
            else:
                current_credits = snapshot.get("credits", 0)
                transaction.update(doc_ref, {
                    "credits": current_credits + amount
                })

        transaction = self.db.transaction()
        transaction_add(transaction)


    def decrement_credits(self, group_id, amount):
        doc_ref = self.group_collection.document(group_id)

        @firestore.transactional
        def transaction_decrement(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise ValueError("Group does not exist")
            current_credits = snapshot.get("credits", 0)
            if current_credits < amount:
                raise ValueError("Not enough credits")
            transaction.update(doc_ref, {
                "credits": current_credits - amount
            })

        transaction = self.db.transaction()
        transaction_decrement(transaction)
