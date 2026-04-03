from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from settings import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    return verify_token(token)


def require_doctor(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    payload = verify_token(token)
    if payload.get("role") != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor role required")
    return payload
