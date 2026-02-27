import os
import sys
import types
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1. Set required env vars BEFORE app imports to satisfy pydantic-settings Fail Fast
os.environ["DATABASE_URL"] = "sqlite:///./dummy.db"
os.environ["SUPABASE_URL"] = "http://test"
os.environ["SUPABASE_KEY"] = "testkey"

# 2. Mock Supabase before it's imported by the app
def make_fake_supabase_module():
    mod = types.ModuleType("supabase")
    
    # Mock Storage
    class FakeBucket:
        def upload(self, file_name, data): return {"error": None}
        def get_public_url(self, file_name): return {"publicURL": f"https://example.com/{file_name}"}
    class Storage:
        def from_(self, name): return FakeBucket()
        
    # Mock Auth
    class FakeAuth:
        def sign_in_with_otp(self, payload): pass
        def verify_otp(self, payload):
            return SimpleNamespace(session=SimpleNamespace(access_token="fake_jwt_token"))
        def get_user(self, token):
            return SimpleNamespace(user=SimpleNamespace(email="tester@gmail.com"))

    def create_client(url, key): 
        return SimpleNamespace(storage=Storage(), auth=FakeAuth())
    
    mod.create_client = create_client
    mod.Client = SimpleNamespace
    return mod

sys.modules["supabase"] = make_fake_supabase_module()

# 3. Import app modules safely
import main as app_module
from app.core.database import get_db
from app.models import Base, User
from app.api.deps import get_current_user

def test_auth_and_upload(tmp_path):
    # 4. Create isolated SQLite test database engine
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # CREATE TABLES (Safe here, strictly targeting the test SQLite environment)
    Base.metadata.create_all(bind=test_engine)

    # Override Database Dependency
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Override the JWT Vault Dependency for testing
    def override_get_current_user():
        db_session = TestingSessionLocal()
        user = db_session.query(User).filter(User.email == "tester@gmail.com").first()
        if not user:
            user = User(email="tester@gmail.com")
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
        return user

    # Apply overrides
    app_module.app.dependency_overrides[get_db] = override_get_db
    app_module.app.dependency_overrides[get_current_user] = override_get_current_user
    
    client = TestClient(app_module.app)

    # --- Run Auth Tests ---
    # Note: We use a valid email domain to bypass our burner shield
    resp1 = client.post("/auth/send-otp/", json={"email": "tester@gmail.com"})
    assert resp1.status_code == 200

    resp2 = client.post("/auth/verify-otp/", json={"email": "tester@gmail.com", "otp": "123456"})
    assert resp2.status_code == 200
    assert "access_token" in resp2.json()

    # --- Run Protected Upload Test ---
    files = {
        "image": ("evidence.jpg", b"\xff\xd8\xff\xdbFAKEJPEGDATA", "image/jpeg")
    }
    data = {
        "latitude": "37.7749",
        "longitude": "-122.4194",
        "category": "shop",
        # user_email is intentionally omitted here because the Vault extracts it from the JWT!
    }
    
    # We don't need to pass the Bearer header here because override_get_current_user intercepts it
    resp3 = client.post("/upload-report/", data=data, files=files)
    assert resp3.status_code == 200, resp3.text
    body = resp3.json()
    assert "reward_points" in body
    assert body["total_points"] >= 0