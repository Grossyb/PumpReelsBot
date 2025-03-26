from google.cloud import storage

class GCSClient:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def upload_file(self, file_bytes, destination_blob_name):
        blob = self.bucket.blob(destination_blob_name)
        blob.upload_from_string(file_bytes, content_type="image/jpeg")
        return f"gs://{self.bucket_name}/{destination_blob_name}"

    def download_file(self, blob_name):
        blob = self.bucket.blob(blob_name)
        return blob.download_as_bytes()

    def delete_file(self, blob_name):
        blob = self.bucket.blob(blob_name)
        blob.delete()
