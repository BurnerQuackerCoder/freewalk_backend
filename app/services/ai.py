import logging
from google import genai
from google.genai import types  # <-- Required for the new SDK to handle raw bytes
from app.core.config import settings

# Initialize the client
client = genai.Client(api_key=settings.GEMINI_API_KEY)

def verify_image_with_ai(image_bytes: bytes, category: str, content_type: str) -> bool:
    """
    Acts as a strict AI inspector. Returns True if the category is present
    in the image, False otherwise.
    """
    try:
        prompt = f"""
        You are a strict municipal evidence inspector.

        Look at this image. Does it clearly contain a civic violation related to '{category}'?

        Examples:
        - If category is 'vehicle', check for illegally parked cars/bikes blocking pathways or on top of footpaths.
        - If category is 'shop', check for temporary street vendors blocking pathways, or on top of footpaths.
        - If category is 'infrastructure', check for illegal permanent structures like railings or slabs on top of footpaths.

        Reply with exactly one word: YES or NO.
        """

        # Correct way to pass raw bytes in the new google-genai SDK
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=content_type,
        )

        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[prompt, image_part],
        )

        text = response.text.strip().upper()

        logging.info(f"AI Inspector Response for {category}: {text}")

        return "YES" in text

    except Exception as e:
        logging.error(f"AI Verification Error: {e}")

        # If AI fails, reject upload (secure default)
        return False