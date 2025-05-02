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
        """
        Returns a list of all group documents where the given creator_id matches.
        """
        query = self.group_collection.where("creator_id", "==", creator_id)
        docs = query.stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data['group_id'] = doc.id
            results.append(data)

        return results


    def add_credits(self, group_id, amount):
        """
        Atomically add `amount` credits to the given `group_id`.
        If the group document doesn’t exist, it will be created.
        """
        doc_ref = self.group_collection.document(group_id)

        def _transaction_add(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                # Group not yet in DB → create with the starting credits
                transaction.set(ref, {
                    "credits": amount,
                    "created_at": firestore.SERVER_TIMESTAMP,  # or Timestamp.now()
                })
            else:
                current_credits = snapshot.get("credits", 0)
                new_credits = current_credits + amount
                transaction.update(ref, {"credits": new_credits})

        self.db.run_transaction(lambda t: _transaction_add(t, doc_ref))


    def decrement_credits(self, group_id, amount):
        doc_ref = self.group_collection.document(group_id)

        def transaction_decrement(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise ValueError("Group does not exist")

            current_credits = snapshot.get("credits", 0)
            if current_credits < amount:
                raise ValueError("Not enough credits")

            new_credits = current_credits - amount
            transaction.update(ref, {"credits": new_credits})

        self.db.run_transaction(lambda t: transaction_decrement(t, doc_ref))
