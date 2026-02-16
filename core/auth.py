from fastapi import Security, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from sqlalchemy.orm import Session
from core.database import SessionLocal, ApiKey
import secrets

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_api_key(
    api_key_header: str = Security(api_key_header),
    db: Session = Depends(get_db)
):
    """
    Validates API Key from header parameter 'X-API-Key'.
    """
    if not api_key_header:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="API Key missing"
        )
    
    key_record = db.query(ApiKey).filter(ApiKey.key == api_key_header, ApiKey.is_active == True).first()
    if key_record:
        return key_record
        
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, detail="Invalid API Key"
    )

def create_new_api_key(owner: str, db: Session) -> str:
    """Generate and save a new API key"""
    new_key = secrets.token_urlsafe(32)
    api_key = ApiKey(key=new_key, owner=owner)
    db.add(api_key)
    db.commit()
    return new_key
