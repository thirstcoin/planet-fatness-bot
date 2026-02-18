import google.generativeai as genai
import PIL.Image
import requests
import os
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
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
            # Relaxed safety is CRITICAL here because "fat" body types 
            # often trigger false positives in AI safety filters.
            relaxed_safety = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]

            template_resp = requests.get(self.template_url, timeout=10)
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            # --- THE "FATNESS" PROMPT ---
            prompt = (
                "STYLE: 2D vector comic art. "
                "TASK: Use the gear-border template as a frame. "
                "Transform the person in the user photo into a massively obese, 'phat' version of themselves. "
                "Give them a very large belly, round soft face, and multiple double chins. "
                "They must look like they have gained 300 pounds of pure fat. "
                "They MUST wear a tight purple tank top that looks too small, with '$PHAT' in bold yellow text on the chest. "
                "Maintain facial likeness so they are recognizable, but much heavier. "
                "No muscles, only soft girth and massive size."
            )

            response = self.model.generate_content(
                [prompt, template_img, user_img],
                safety_settings=relaxed_safety
            )
            
            if response.candidates and len(response.candidates[0].content.parts) > 0:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        return part.inline_data.data
            
            if response.prompt_feedback:
                logger.warning(f"⚠️ Synthesis Blocked: {response.prompt_feedback}")
                
            return None

        except Exception as e:
            logger.error(f"❌ AI Generation Error: {e}")
            return None
