import os
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

    def send_message(self, to_number: str, message_text: str, preview_url: bool = False) -> Dict[str, Any]:
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
                "preview_url": bool(preview_url),
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

    def send_image(self, to_number: str, image_url: str, caption: str = "") -> Dict[str, Any]:
        """
        Send an image message using WhatsApp Graph API
        """
        url = f"{self.base_url}/{self.phone_id}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "image",
            "image": {
                "link": image_url,
                "caption": caption
            }
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Image Send Failed: {e}")
            if e.response:
                print(f"Response: {e.response.text}")
            return {"error": str(e)}

    def send_video(self, to: str, url: str, caption: str = "") -> Dict[str, Any]:
        """Send a video message"""
        media_url = url
        api_url = f"{self.base_url}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "video",
            "video": {"link": media_url, "caption": caption}
        }
        try:
            response = requests.post(api_url, headers=self.headers, json=payload, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Video Send Failed: {e}")
            return {"error": str(e)}

    def send_document(self, to: str, url: str, caption: str = "", filename: str = "") -> Dict[str, Any]:
        """Send a document message"""
        document_url = url
        api_url = f"{self.base_url}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {
                "link": document_url,
                "caption": caption,
                "filename": filename
            }
        }
        try:
            response = requests.post(api_url, headers=self.headers, json=payload, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Document Send Failed: {e}")
            return {"error": str(e)}

    def send_location(self, to: str, lat: float, long: float, name: str, address: str) -> Dict[str, Any]:
        """Send a location message"""
        url = f"{self.base_url}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "location",
            "location": {
                "latitude": lat,
                "longitude": long,
                "name": name,
                "address": address
            }
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Location Send Failed: {e}")
            return {"error": str(e)}

    def send_interactive_buttons(self, to: str, body_text: str, buttons_list: list) -> Dict[str, Any]:
        """
        Send an interactive message with buttons (limit 3).
        buttons: List of {"id": "btn_1", "title": "Option 1"}
        """
        url = f"{self.base_url}/{self.phone_id}/messages"
        
        # WhatsApp limits buttons to 3
        safe_buttons = buttons_list[:3]
        
        button_actions = []
        for btn in safe_buttons:
            button_actions.append({
                "type": "reply",
                "reply": {
                    "id": btn.get("id"),
                    "title": btn.get("title")[:20] # Title limit 20 chars
                }
            })
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": button_actions}
            }
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Buttons Send Failed: {e}")
            return {"error": str(e)}


    def send_interactive_message(self, to_number: str, text: str, buttons: list) -> Dict[str, Any]:
        """
        Send an interactive message with buttons
        buttons: List of {"id": "1", "title": "Buy"}
        """
        url = f"{self.base_url}/{self.phone_id}/messages"
        
        button_actions = []
        for btn in buttons:
            button_actions.append({
                "type": "reply",
                "reply": {
                    "id": btn.get("id"),
                    "title": btn.get("title")
                }
            })
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": button_actions
                }
            }
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Interactive Send Failed: {e}")
            return {"error": str(e)}

    def send_flow_message(self, to_number: str, flow_id: str, flow_token: str, 
                         header: str, body: str, footer: str, cta: str,
                         screen: str, data: dict = {}) -> Dict[str, Any]:
        """
        Send a WhatsApp Flow message
        """
        url = f"{self.base_url}/{self.phone_id}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "flow",
                "header": {
                    "type": "text",
                    "text": header
                },
                "body": {
                    "text": body
                },
                "footer": {
                    "text": footer
                },
                "action": {
                    "name": "flow",
                    "parameters": {
                        "mode": os.getenv("WHATSAPP_FLOW_MODE", "published"),
                        "flow_message_version": "3",
                        "flow_token": flow_token,
                        "flow_id": flow_id,
                        "flow_cta": cta,
                        "flow_action": "navigate",
                        "flow_action_payload": {
                            "screen": screen,
                            "data": data
                        }
                    }
                }
            }
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ WhatsApp Flow Send Failed: {e}")
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
            
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                itype = interactive.get("type")
                
                if itype == "button_reply":
                    result["text"] = interactive.get("button_reply", {}).get("title") # Treat title as text query
                    result["payload"] = interactive.get("button_reply", {}).get("id")
                    result["interaction_type"] = "button_reply"
                
                elif itype == "nfm_reply": # Flow response
                    result["response_json"] = interactive.get("nfm_reply", {}).get("response_json")
                    result["interaction_type"] = "flow_response"
                    # We might want to construct a text representation or just set a special flag
                    result["text"] = "[FLOW_RESPONSE]" 
                
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
