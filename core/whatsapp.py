import requests
import json
from typing import Dict, Any, Optional
from core.config import WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_API_VERSION

class WhatsAppHandler:
    def __init__(self):
        self.base_url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        self.token = WHATSAPP_ACCESS_TOKEN
        self.phone_id = WHATSAPP_PHONE_ID
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def send_message(self, to_number: str, message_text: str) -> Dict[str, Any]:
        """
        Send a text message using WhatsApp Graph API
        """
        url = f"{self.base_url}/{self.phone_id}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message_text
            }
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Send Failed: {e}")
            if e.response:
                print(f"Response: {e.response.text}")
            return {"error": str(e)}

    @staticmethod
    def extract_message_from_webhook(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Extract user number and message body from Meta Webhook payload.
        Returns None if not a valid message.
        """
        try:
            entry = payload.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])
            
            if not messages:
                return None
                
            msg = messages[0]
            msg_type = msg.get("type")
            
            result = {
                "user_id": msg.get("from"),
                "message_id": msg.get("id"),
                "name": value.get("contacts", [{}])[0].get("profile", {}).get("name", "Unknown"),
                "type": msg_type
            }

            if msg_type == "text":
                result["text"] = msg.get("text", {}).get("body")
                return result
            
            elif msg_type == "audio":
                audio_meta = msg.get("audio", {})
                result["audio"] = {
                    "id": audio_meta.get("id"),
                    "mime_type": audio_meta.get("mime_type")
                }
                return result

            return None
        except (IndexError, AttributeError):
            return None

    def get_media_url(self, media_id: str) -> Optional[str]:
        """Get the download URL for a media ID"""
        url = f"{self.base_url}/{media_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get("url")
        except Exception as e:
            print(f"❌ Failed to get media URL: {e}")
            return None

    def download_media(self, media_url: str) -> Optional[bytes]:
        """Download media binary data"""
        try:
            # Note: Media download requires Authorization header
            response = requests.get(media_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"❌ Media download failed: {e}")
            return None
