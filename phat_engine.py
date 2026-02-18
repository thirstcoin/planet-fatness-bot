import google.generativeai as genai
import PIL.Image
import requests
import os
import logging
import sys
from io import BytesIO
from google.generativeai import types # Required for 2026 config types

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            # 2026 FIX: Must use the specific '-image' variant for generation
            self.model_id = 'gemini-2.5-flash-image' 
            self.model = genai.GenerativeModel(self.model_id)
            print(f"✅ PhatEngine initialized with {self.model_id}", flush=True)
        else:
            self.model = None
            logger.error("❌ GEMINI_API_KEY missing.")
            
        self.template_url = "https://i.postimg.cc/5NqxCS7j/IMG-2610.jpg"

    def generate_phat_image(self, user_img_bytes):
        if not self.model:
            return None

        try:
            # 2026 IMAGE CONFIG: Requires response_modalities set to IMAGE
            # This prevents the 'text output only' 400 error.
            generation_config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                temperature=1.0
            )

            print("🔄 Fetching assets...", flush=True)
            template_resp = requests.get(self.template_url, timeout=10)
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            # BYPASS PROMPT: Focus on 'Cartoon Parody'
            prompt = (
                "Transform the person in the user photo into a stylized, $PHAT cartoon character. "
                "The character should have massively round, voluminous proportions and double chins. "
                "They MUST wear a tight purple tank top with '$PHAT' in bold yellow text. "
                "Use the gear-border template as a frame. Maintain the facial likeness."
            )

            print(f"🚀 Calling {self.model_id}...", flush=True)
            # Note: In 2026 SDK, generation_config is passed as 'config'
            response = self.model.generate_content(
                [prompt, template_img, user_img],
                generation_config=generation_config
            )
            
            # Extraction logic for image data
            if response.candidates and len(response.candidates[0].content.parts) > 0:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        print("✨ SUCCESS: Image synthesized.", flush=True)
                        return part.inline_data.data
            
            return None

        except Exception as e:
            print(f"❌ API FAILURE: {str(e)}", file=sys.stderr, flush=True)
            return None
