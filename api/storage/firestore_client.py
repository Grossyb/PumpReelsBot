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
            doc['group_id'] = doc.id
            return doc.to_dict()

        return None


    def get_groups_by_creator(self, creator_id):
        """
        Returns a list of all group documents where the given creator_id matches.
        """
        query = self.group_collection.where("creator_id", "==", creator_id)
        docs = query.stream()
        return [doc.to_dict() for doc in docs]


    def add_credits(self, group_id, amount):
        """
        Atomically add `amount` credits to the given `group_id`.
        • If the group document doesn’t exist, it will be created with the initial balance.
        """
        doc_ref = self.group_collection.document(group_id)

        def _transaction_add(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                # Group not yet in DB → create with the starting credits
                transaction.set(ref, {
                    "credits": amount,
                    "created_at": Timestamp.now(),   # optional: if you want metadata
                })
                return

        current_credits = snapshot.get("credits", default=0)
        new_credits = current_credits + amount
        transaction.update(ref, {"credits": new_credits})

        # Run the anonymous transactional function
        self.db.run_transaction(lambda t: _transaction_add(t, doc_ref))


    def decrement_credits(self, group_id, amount):
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
