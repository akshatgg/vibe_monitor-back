import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Settings:
    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI")
    
    # Other settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")

settings = Settings()