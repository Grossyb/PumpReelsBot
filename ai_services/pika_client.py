import requests

class PikaClient:
    def __init__(self):
        self.api_key = 'OD6N9H0wT1HzEhsxH-AcqkW48Rwdyta36GcSNqKuWZE'
        self.base_url = 'https://devapi.pika.art'


    def generate_video(image, prompt_text, negative_prompt, duration, resolution):
        payload = {
            "promptText": prompt_text,
            "negativePrompt": negative_prompt,
            "seed": 12345,
            "duration": duration,
            "resolution": resolution
        }
        headers = {
            "X-API-KEY": self.api_key,
            "Accept": "application/json"
        }
        files = {
            "image": image
        }
        url = f"{self.base_url}/generate/2.2/i2v"

        response = requests.post(url, data=payload, headers=headers, files=files)

        return response.json


    def check_video_status(self, video_id):
        url = f"{self.base_url}/videos/{video_id}"
        headers = {
            "X-API-KEY": self.api_key,
            "Accept": "application/json"
        }

        response = requests.get(url, headers=headers)
        return response.json()
