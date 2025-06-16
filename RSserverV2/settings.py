from dotenv import load_dotenv
import os
from functools import lru_cache


load_dotenv()

class Settings:
    RS_HOST: str = os.getenv("RS_HOST","0.0.0.0")
    RS_PORT: int = int(os.getenv("RS_PORT","8000"))
    RS_WIDTH: int = int(os.getenv("RS_WIDTH","640"))
    RS_HEIGHT: int = int(os.getenv("RS_HEIGHT","480"))
    RS_FPS: int = int(os.getenv("RS_FPS","30"))

@lru_cache
def get_settings() -> Settings:
    return Settings()