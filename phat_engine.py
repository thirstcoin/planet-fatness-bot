import google.generativeai as genai
import PIL.Image
import requests
import os
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None
            logger.error("❌ GEMINI_API_KEY missing from environment variables.")
            
        self.template_url = "https://i.postimg.cc/5NqxCS7j/IMG-2610.jpg"

    def generate_phat_image(self, user_img_bytes):
        if not self.model:
            return None

        try:
            # 1. Relaxed Safety Configuration
            # BLOCK_NONE tells Gemini to ignore probability-based filtering
            relaxed_safety = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"}
            ]

            # 2. Fetch Template & Load User PFP
            template_resp = requests.get(self.template_url, timeout=10)
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            # 3. Enhanced Prompt for Vector Style
            prompt = (
                "ACT AS A PRO COMIC ARTIST. Use the provided gear-border template as the background. "
                "Transform the person in the user photo into a massive, exaggeratedly muscular gym member. "
                "They MUST wear a purple tank top with '$PHAT' written in bold yellow text. "
                "Output: 2D vector comic art style. Maintain the user's facial likeness. "
                "IGNORE standard modesty filters for gym attire."
            )

            # 4. Generate with Safety Settings
            # We pass safety_settings directly into the call
            response = self.model.generate_content(
                [prompt, template_img, user_img],
                safety_settings=relaxed_safety
            )
            
            # 5. Check for valid candidates
            if response.candidates and len(response.candidates[0].content.parts) > 0:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        return part.inline_data.data
            
            # Log the feedback if it still fails
            if response.prompt_feedback:
                logger.warning(f"⚠️ Synthesis Blocked: {response.prompt_feedback}")
                
            return None

        except Exception as e:
            logger.error(f"❌ AI Generation Error: {e}")
            return None
