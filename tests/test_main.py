import os
import sys
import types
import importlib
from types import SimpleNamespace
from fastapi.testclient import TestClient
import io


def make_fake_supabase_module():
    """Return a fake `supabase` module with a create_client function used by main.py."""
    mod = types.ModuleType("supabase")

    class FakeBucket:
        def upload(self, file_name, data):
            return {"error": None}

        def get_public_url(self, file_name):
            return {"publicURL": f"https://example.com/{file_name}"}

    class Storage:
        def from_(self, name):
            return FakeBucket()

    def create_client(url, key):
        return SimpleNamespace(storage=Storage())

    mod.create_client = create_client
    mod.Client = SimpleNamespace
    return mod


def test_login_and_upload_report(tmp_path, monkeypatch):
    # Prepare environment for main import: use a file-backed sqlite so tables persist
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SUPABASE_URL"] = "http://test"
    os.environ["SUPABASE_KEY"] = "testkey"
    os.environ["AUTO_CREATE_TABLES"] = "true"

    # Inject fake supabase module before importing main
    fake_supabase = make_fake_supabase_module()
    sys.modules["supabase"] = fake_supabase

    # Import (or reload) the application module
    import main as app_module
    importlib.reload(app_module)

    client = TestClient(app_module.app)

    # 1) Login (create user)
    resp = client.post("/login/", data={"email": "tester@example.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert "user_id" in body
    assert body["email"] == "tester@example.com"

    # 2) Upload report
    files = {
        "image": ("evidence.jpg", b"\xff\xd8\xff\xdbFAKEJPEGDATA", "image/jpeg")
    }
    data = {
        "latitude": "37.7749",
        "longitude": "-122.4194",
        "category": "shop",
        "user_email": "tester@example.com",
    }

    resp2 = client.post("/upload-report/", data=data, files=files)
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert "reward_points" in body2
    assert body2["total_points"] >= 0
 