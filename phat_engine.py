import google.generativeai as genai
import PIL.Image
import requests
import os
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
        # Configure Gemini - Ensure GEMINI_API_KEY is in Render Env
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None
            logger.error("❌ GEMINI_API_KEY missing from environment variables.")
            
        # Your locked Direct Link
        self.template_url = "https://i.postimg.cc/5NqxCS7j/IMG-2610.jpg"

    def generate_phat_image(self, user_img_bytes):
        if not self.model:
            return None

        try:
            # 1. Fetch the Gear Template
            template_resp = requests.get(self.template_url, timeout=10)
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            
            # 2. Load User PFP
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            # 3. The Vision Prompt
            prompt = (
                "Use the provided gear-border template as the background frame. "
                "Transform the person in the user photo into a massive, muscular 'phat' gym member. "
                "They must wear a purple tank top with yellow '$PHAT' text. "
                "Style: 2D vector comic art. Maintain facial likeness."
            )

            # 4. Generate
            response = self.model.generate_content([prompt, template_img, user_img])
            
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    return part.inline_data.data
            return None
        except Exception as e:
            logger.error(f"AI Generation Error: {e}")
            return None
