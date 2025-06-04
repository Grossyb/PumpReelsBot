from firebase_admin import credentials, firestore, storage, initialize_app
from pandas import Timestamp
import firebase_admin
import uuid


class FirestoreClient:
    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.Certificate('/secrets/pumpreels/pumpreels_service_key.json')
            initialize_app(cred)

        self.db = firestore.client()
        self.group_collection = self.db.collection('groups')
        self.transaction_collection = self.db.collection('transactions')


    def create_transaction(self, data: dict):
        """
        Create a transaction document in Firestore based on Radom's managedPayment webhook payload.
        """
        try:
            checkout = data["radomData"]["checkoutSession"]
            payment = data["eventData"]["managedPayment"]
            tx = payment["transactions"][0]  # Assuming 1 transaction per payment

            # Extract metadata
            metadata = {item["key"]: item["value"] for item in checkout.get("metadata", [])}
            group_id = metadata.get("telegram_group_id")
            credits = int(metadata.get("credits_str", 0))

            doc_id = checkout["checkoutSessionId"]

            # Essential fields
            payment_id = doc_id
            transaction_hash = tx.get("transactionHash")
            status = "pending"
            created_at = Timestamp.now()

            # Helpful additional fields
            network = tx.get("network")
            ticker = tx.get("ticker")
            amount = tx.get("amount")
            sender_address = tx.get("senderAddresses", [{}])[0].get("address")

            usd_value = payment["paymentSummary"].get("grossAmount")
            net_amount = payment["paymentSummary"].get("netAmount")
            network_fee_amount = payment["paymentSummary"].get("networkFeeAmount")

            # Firestore document
            transaction_doc = {
                "group_id": group_id,
                "credits": credits,
                "status": status,
                "transaction_hash": transaction_hash,
                "network": network,
                "ticker": ticker,
                "amount": amount,
                "usd_value": usd_value,
                "net_amount": net_amount,
                "network_fee_amount": network_fee_amount,
                "sender_address": sender_address,
                "created_at": created_at,
                "confirmed_at": None
            }

            self.transaction_collection.document(payment_id).set(transaction_doc)

        except Exception as e:
            print(f"Failed to create transaction: {e}")
            raise e


    def confirm_transaction_by_tx_hash(self, transaction_hash: str):
        """
        Confirm a transaction based on its blockchain transaction hash.
        Adds credits to the appropriate group and updates the transaction status.
        """
        docs = self.transaction_collection.where("transaction_hash", "==", transaction_hash).limit(1).stream()

        for doc in docs:
            tx = doc.to_dict()

            if tx.get("status") == "confirmed":
                return "already_confirmed"

            group_id = tx.get("group_id")
            credits = tx.get("credits")

            # Add credits to the group
            self.add_credits(group_id, credits)

            # Mark as confirmed
            doc.reference.update({
                "status": "confirmed",
                "confirmed_at": Timestamp.now()
            })

            return group_id

        return None


    # def create_group(self, data, creator_user_id):
    #     group_id = str(data['id'])
    #
    #     doc_ref = self.group_collection.document(group_id)
    #     doc_ref.set({
    #         "title": data['title'],
    #         "type": data['type'],
    #         "creator_id": creator_user_id,
    #         "credits": 0,
    #         "created_at": Timestamp.now()
    #     })
    #
    #     return doc_ref.id

    def create_group(self, data, creator_user_id, creator_username, creator_full_name):
        doc_id = "g_" + uuid.uuid4().hex
        group_id = str(data['id'])

        doc_ref = self.group_collection.document(doc_id)
        doc_ref.set({
            "title": data['title'],
            "type": data['type'],
            "group_id": group_id,
            "creator_id": creator_user_id,
            "creator_username": creator_username,
            "creator_full_name": creator_full_name,
            "credits": 0,
            "created_at": Timestamp.now()
        })

        return doc_ref.id

    def get_group(self, group_id):
        query = self.group_collection.where('group_id', '==', group_id).limit(1).stream()

        for doc in query:
            data = doc.to_dict()
            data['doc_id'] = doc.id  # optional: if you still want to know the document ID
            return data

        return None

    # def get_group(self, group_id):
    #     doc_ref = self.group_collection.document(group_id)
    #     doc = doc_ref.get()
    #
    #     if doc.exists:
    #         data = doc.to_dict()
    #         data['group_id'] = doc.id
    #         return data
    #
    #     return None

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
                current_credits = snapshot.get("credits") or 0
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
            current_credits = snapshot.get("credits") or 0
            if current_credits < amount:
                raise ValueError("Not enough credits")
            transaction.update(doc_ref, {
                "credits": current_credits - amount
            })

        transaction = self.db.transaction()
        transaction_decrement(transaction)
