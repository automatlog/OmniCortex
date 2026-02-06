import requests
import json
from datetime import datetime

# Webhook URL
webhook_url = "https://hooks.zapier.com/hooks/catch/25425445/uq92mqi/"

# WhatsApp Business Account webhook notification payload
payload = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "1926713144945445",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15558414008",
                            "phone_number_id": "879654938564926"
                        },
                        "name": "Aman Yadav",
                        "statuses": [
                            {
                                "id": "wamid.HBgMOTE5NDI4NTg3ODE3FQIAERgSQTdFREI2MEUwOTFFMUU2NTNCAA==",
                                "status": "delivered",
                                "timestamp": "1766149881",
                                "recipient_id": "919428587817",
                                "biz_opaque_callback_data": "1_8176617798474858496_0_393_380_3836",
                                "pricing": {
                                    "billable": True,
                                    "pricing_model": "PMP",
                                    "category": "marketing_lite",
                                    "type": "regular"
                                }
                            }
                        ]
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}

print("📡 Sending webhook to Zapier...")
print(f"URL: {webhook_url}")
print(f"\n📦 Payload:")
print(json.dumps(payload, indent=2))

try:
    # Send POST request
    response = requests.post(
        webhook_url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "RAG-Chatbot-Webhook-Test"
        },
        timeout=10
    )
    
    print(f"\n✅ Response Status: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    
    if response.text:
        print(f"Response Body: {response.text}")
    else:
        print("Response Body: (empty)")
    
    if response.status_code == 200:
        print("\n🎉 Webhook sent successfully!")
    else:
        print(f"\n⚠️ Unexpected status code: {response.status_code}")
        
except requests.exceptions.Timeout:
    print("\n❌ Error: Request timed out")
except requests.exceptions.ConnectionError:
    print("\n❌ Error: Connection failed")
except Exception as e:
    print(f"\n❌ Error: {str(e)}")
