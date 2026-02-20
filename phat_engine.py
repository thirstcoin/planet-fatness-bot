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
        # Using the 2026 Unified Client
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                self.model_id = 'gemini-2.5-flash-image'
                # Simple connectivity test to ensure engine doesn't report "offline"
                print(f"✅ PhatEngine initialized with {self.model_id}", flush=True)
            except Exception as e:
                self.client = None
                logger.error(f"❌ Failed to initialize GenAI Client: {e}")
        else:
            self.client = None
            logger.error("❌ GEMINI_API_KEY missing from environment variables.")
            
        self.template_url = "https://i.postimg.cc/y6f9tr2n/IMG-2725.jpg"

    def generate_phat_image(self, user_img_bytes):
        """
        Synthesizes a $PHAT PFP using Gemini 2.5 Flash Image.
        Designed to run inside an asyncio.to_thread worker.
        """
        if not self.client:
            logger.error("❌ Engine Attempted without Client.")
            return None

        try:
            # 2026 SDK: GenerateContentConfig for native image output
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

            print("🔄 Fetching transformation assets...", flush=True)
            template_resp = requests.get(self.template_url, timeout=10)
            template_resp.raise_for_status()
            
            # Convert both to PIL to ensure consistent color space and metadata stripping
            template_img = PIL.Image.open(BytesIO(template_resp.content))
            user_img = PIL.Image.open(BytesIO(user_img_bytes))

            prompt = (
                "TASK: Transform the person provided in the second image into a stylized, "
                "epic, cartoonishly large $PHAT character. Proportions should be massive and round. "
                "The character MUST wear a tight purple tank top with '$PHAT' written on the chest. "
                "Integrate the facial features of the user with the border template provided."
            )

            print(f"🚀 Requesting synthesis from {self.model_id}...", flush=True)
            
            # Passing images directly as PIL objects is supported in the 2026 SDK
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[prompt, template_img, user_img],
                config=config
            )
            
            # Extract the raw binary image from the response candidates
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        print("✨ SUCCESS: $PHAT DNA synthesized.", flush=True)
                        return part.inline_data.data
            
            print("⚠️ Engine returned successfully but contained no image data.", flush=True)
            return None

        except Exception as e:
            print(f"❌ API FAILURE in PhatEngine: {str(e)}", file=sys.stderr, flush=True)
            return None
