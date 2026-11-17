import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET = os.getenv("SECRET_KEY", "development-secret-change-before-deploy")
oauth = OAuth2PasswordBearer(tokenUrl="/api/login")

def hash_password(value): return pwd.hash(value)
def check_password(value, hashed): return pwd.verify(value, hashed)
def make_token(user):
    return jwt.encode({"sub": str(user.id), "exp": datetime.utcnow()+timedelta(hours=36)}, SECRET, algorithm="HS256")

def get_user(token=Depends(oauth), db: Session=Depends(get_db)):
    try:
        uid = int(jwt.decode(token, SECRET, algorithms=["HS256"])["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(401, "Войдите в аккаунт")
    user = db.get(User, uid)
    if not user: raise HTTPException(401, "Аккаунт не найден")
    return user

def roles(*allowed):
    def guard(user: User=Depends(get_user)):
        if user.role not in allowed: raise HTTPException(403, "Недостаточно прав")
        return user
    return guard
