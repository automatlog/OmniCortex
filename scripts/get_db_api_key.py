
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from core.database import SessionLocal, ApiKey, init_db
from core.auth import create_new_api_key

def get_or_create_key():
    db = SessionLocal()
    try:
        # Try to find existing active key
        key = db.query(ApiKey).filter(ApiKey.is_active == True).first()
        final_key = ""
        if key:
            final_key = key.key
            print(f"FOUND_KEY: {final_key}")
        else:
            print("No keys found. Creating new...")
            final_key = create_new_api_key("stress_test_user", db)
            print(f"CREATED_KEY: {final_key}")
        
        with open("temp_api_key.txt", "w") as f:
            f.write(final_key)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    get_or_create_key()
