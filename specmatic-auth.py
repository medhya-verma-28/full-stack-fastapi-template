import jwt
from datetime import datetime, timedelta, timezone

# 1. Define configuration constants
SECRET_KEY = "your-secret-key"  # Must match the app's secret key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict) -> str:
    """Generates a secure JWT access token."""
    to_encode = data.copy()
    
    # Calculate expiration time using timezone-aware UTC
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    
    # Encode and sign the payload
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Example Usage:
user_payload = {"sub": "user_123", "role": "admin"}
token = create_access_token(data=user_payload)
print(f"Bearer {token}")
