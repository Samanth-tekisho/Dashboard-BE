from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt

PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "CHANGE_ME_IN_PRODUCTION" # TODO: Move to config
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# Logic moved to backend.app.utils

