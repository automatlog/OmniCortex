
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

def write_bearer_token():
    token = (os.getenv("BEARER_TOKEN") or os.getenv("AUTH_BEARER_TOKEN") or "").strip()
    if not token:
        print("Error: BEARER_TOKEN (or AUTH_BEARER_TOKEN) is required")
        sys.exit(1)
    with open("temp_api_key.txt", "w", encoding="utf-8") as f:
        f.write(token)
    print("TOKEN_WRITTEN: temp_api_key.txt")

if __name__ == "__main__":
    write_bearer_token()
