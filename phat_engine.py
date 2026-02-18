import google.generativeai as genai
import PIL.Image
import requests
import os
import logging
import sys
from io import BytesIO

logger = logging.getLogger(__name__)

class PhatEngine:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            # UPDATED: gemini-1.5-flash is retired. Use gemini-2.5-flash for stable Tier 1.
            self.model = genai.GenerativeModel('gemini-2.5-flash')
            print("✅ PhatEngine initialized with Gemini 2.5 Flash", flush=True)
        else:
            self.model = None
            logger.error("❌ GEMINI_API_KEY missing from environment variables.")
            print("❌ ERROR: Missing API Key", file=sys.stderr, flush=True)
            
        self.template_url = "https://i.postimg.cc/5NqxCS7j/IMG-2610.jpg"

    def generate_phat_image(self, user_img_bytes):
        if not self.model:
            return None

        try:
            # Using BLOCK_NONE is correct for Tier 1 to avoid "Safety" false positives
            relaxed_safety = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]

            print("🔄 Fetching template and processing user image...", flush=True)
            template_resp = requests.get(self.template_url, timeout=10)
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            # --- THE "FATNESS" PROMPT (Polished for 2026 LLM comprehension) ---
            prompt = (
                "STYLE: 2D vector comic art. "
                "TASK: Use the gear-border template as a frame. "
                "Transform the person in the user photo into a massively voluminous, 'phat' version of themselves. "
                "Give them an extremely large belly, round soft facial features, and pronounced double chins. "
                "The subject should appear as if they have gained significant weight. "
                "They MUST wear a tight purple tank top that looks too small, with '$PHAT' in bold yellow text on the chest. "
                "Maintain facial likeness for recognition, but emphasize soft girth and massive size."
            )

            print(f"🚀 Sending request to Gemini 2.5 Flash...", flush=True)
            response = self.model.generate_content(
                [prompt, template_img, user_img],
                safety_settings=relaxed_safety
            )
            
            # 2026 SDK check: verifying image data in the response parts
            if response.candidates and len(response.candidates[0].content.parts) > 0:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        print("✨ Image synthesis successful!", flush=True)
                        return part.inline_data.data
            
            # Catching Safety/Recitation blocks in the logs
            if response.prompt_feedback:
                print(f"⚠️ Synthesis Blocked by Google: {response.prompt_feedback}", flush=True)
                logger.warning(f"⚠️ Synthesis Blocked: {response.prompt_feedback}")
                
            return None

        except Exception as e:
            # This will now show up clearly in your Render logs
            print(f"❌ CRITICAL AI ERROR: {str(e)}", file=sys.stderr, flush=True)
            logger.error(f"❌ AI Generation Error: {e}")
            return None
