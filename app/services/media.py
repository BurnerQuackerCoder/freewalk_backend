import os
import uuid
import logging
from typing import Optional
from supabase import create_client, Client
from app.core.config import settings

try:
    import imghdr as _imghdr
except Exception:
    _imghdr = None

try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = None

# Initialize Supabase Client directly. Config already enforces required env vars.
# We cast to str() to satisfy Pylance since config types them as Optional[str]
supabase: Client = create_client(str(settings.SUPABASE_URL), str(settings.SUPABASE_KEY))

def detect_image_type_from_bytes(file_bytes: bytes) -> Optional[str]:
    """Return a short image type string like 'jpeg' or 'png', or None if unknown."""
    if _imghdr is not None:
        try:
            return _imghdr.what(None, h=file_bytes)
        except Exception:
            pass
    if _PILImage is not None:
        try:
            from io import BytesIO
            with _PILImage.open(BytesIO(file_bytes)) as img:
                fmt = (img.format or "").lower()
                if fmt in ("jpeg", "png"):
                    return fmt
        except Exception:
            pass
    return None

def upload_image_to_storage(file_bytes: bytes, filename: Optional[str], content_type: str) -> str:
    """Uploads an image to Supabase and returns the public URL.
    Note: 'evidence-images' bucket ACL must be configured as Public in Supabase."""
    _, ext = os.path.splitext(filename or "")
    ext = ext.lower()
    if not ext:
        if content_type == "image/jpeg":
            ext = ".jpg"
        elif content_type == "image/png":
            ext = ".png"
            
    file_name = f"{uuid.uuid4().hex}{ext}"

    bucket = supabase.storage.from_("evidence-images")

    try:
       bucket.upload(file_name, file_bytes)
    except Exception as e:
        logging.exception("Supabase upload failed")
        raise RuntimeError("Failed to upload image to cloud storage")

    try:
        pub_res = bucket.get_public_url(file_name)
        public_image_url = None
        if isinstance(pub_res, dict):
            public_image_url = pub_res.get("publicURL") or pub_res.get("public_url") or (pub_res.get("data") or {}).get("publicUrl")
        else:
            public_image_url = str(pub_res)
        if not public_image_url:
            raise ValueError("No public URL returned")
        return public_image_url
    except Exception:
        logging.exception("Failed to obtain public URL from Supabase")
        raise RuntimeError("Failed to obtain public image URL")