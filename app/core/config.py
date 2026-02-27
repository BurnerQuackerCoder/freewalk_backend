from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Required Secrets (No defaults, will fail fast if missing)
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    
    # Configurable Business Logic (With safe defaults)
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024
    NEARBY_METERS: float = 5.0
    RECENT_HOURS: int = 24
    AUTO_CREATE_TABLES: bool = False

    # --- NEW: Reward System Configuration ---
    REWARD_NEW_VIOLATION: int = 50
    REWARD_CONFIRMED_VIOLATION: int = 10

    # Pydantic v2 config to read from .env file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

# Instantiate as a singleton to be imported across the app
settings = Settings()

# Fail Fast validation for the required variables
if not settings.DATABASE_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")
if not settings.SUPABASE_URL:
    raise RuntimeError("Missing required env var: SUPABASE_URL")
if not settings.SUPABASE_KEY:
    raise RuntimeError("Missing required env var: SUPABASE_KEY")