import os
import logging
import requests
import PIL.Image
import sys
from io import BytesIO
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
        # We use the new 2026 Unified Client
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
            # Use the specialized image variant
            self.model_id = 'gemini-2.5-flash-image'
            print(f"✅ PhatEngine initialized with {self.model_id}", flush=True)
        else:
            self.client = None
            logger.error("❌ GEMINI_API_KEY missing from environment variables.")
            
        self.template_url = "https://i.postimg.cc/5NqxCS7j/IMG-2610.jpg"

    def generate_phat_image(self, user_img_bytes):
        if not self.client:
            return None

        try:
            # 2026 UNIFIED CONFIG: 
            # This is the correct way to request image output in the new SDK
            config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                temperature=1.0,
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE")
                ]
            )

            print("🔄 Fetching assets...", flush=True)
            template_resp = requests.get(self.template_url, timeout=10)
            
            # 2026 SDK requires images to be passed as types.Part or PIL objects
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            prompt = (
                "TASK: Transform the person into a stylized, epic, cartoonishly large $PHAT character. "
                "The character has massive, round, comic-book style proportions and multiple chins. "
                "They MUST wear a tight purple tank top with '$PHAT' written on the chest. "
                "Use the gear-border template as a frame. Maintain the facial features of the user."
            )

            print(f"🚀 Requesting synthesis from {self.model_id}...", flush=True)
            
            # Using the new model generation method
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, template_img, user_img],
                config=config
            )
            
            # Extract image bytes from the response parts
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    print("✨ SUCCESS: Image data received.", flush=True)
                    return part.inline_data.data
            
            print("⚠️ No image data found in response parts.", flush=True)
            return None

        except Exception as e:
            print(f"❌ API FAILURE: {str(e)}", file=sys.stderr, flush=True)
            return None
