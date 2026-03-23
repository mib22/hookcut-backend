import os
import requests
import cloudinary
import cloudinary.uploader
import google.genai as genai
from fastapi import FastAPI, UploadFile, File
from dotenv import load_dotenv
import uvicorn

load_dotenv()

app = FastAPI()

@app.get("/")
def home():
    return {"message": "HookCut AI Backend is Running"}

# --- CONFIGURATION ---
# Cloudinary Keys
cloudinary.config( 
  cloud_name = "do76w2ke2", 
  api_key = "562397812131958", 
  api_secret = "rB_fTxfHsbnqAR9ZREeaCcX5EH8",
  secure = True
)

# Other Keys
CREATOMATE_API_KEY = "295c6ed0f5384ea9b326b5d3f94caa2797efbdc100766ec46c2b1003f161e4a60fd00fd4b10f44f526dacc9421cdc1e0"
genai.configure(api_key="AIzaSyDCj80sHjFNJAwRdmayNQ09A0Y6wDxl1II")

@app.post("/create-viral-edit")
async def create_viral_edit(file: UploadFile = File(...)):
    # 1. Upload to Cloudinary to get a public URL
    # Creatomate needs a URL to "see" the video
    upload_result = cloudinary.uploader.upload(file.file, resource_type="video")
    video_url = upload_result.get("secure_url")

    # 2. Let Gemini analyze the video for the best 5-second hook
    # We use the Cloudinary URL so we don't have to re-upload
    model = genai.GenerativeModel('gemini-3-flash') # Or gemini-3-flash in 2026
    
    # Prompting Gemini to return JSON instructions
    prompt = f"""
    Analyze this video: {video_url}
    Identify the most engaging 5-second 'hook' moment.
    Return ONLY JSON: 
    {{ "start": (seconds), "caption": "Viral text for overlay" }}
    """
    
    # Note: In a production app, you'd use genai.upload_file for better analysis
    # For this 'Easy' version, we'll assume Gemini processes the URL
    response = model.generate_content(prompt)
    # Simple extraction of the JSON part
    import json
    import re
    clean_json = re.search(r'\{.*\}', response.text, re.DOTALL).group()
    edit_instructions = json.loads(clean_json)

    # 3. Tell Creatomate to Render the final video
    render_data = {
        "output_format": "mp4",
        "source": {
            "duration": 5, # We want a short, punchy clip
            "elements": [
                {
                    "type": "video",
                    "source": video_url,
                    "trim_start": edit_instructions['start'],
                    "width": "100%",
                    "height": "100%",
                    "smart_crop": True # 2026 feature: automatically centers the action
                },
                {
                    "type": "text",
                    "text": edit_instructions['caption'],
                    "font": "Montserrat ExtraBold",
                    "y": "75%",
                    "background_color": "rgba(0,0,0,0.6)",
                    "padding": "2%"
                }
            ]
        }
    }

    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json"
    }

    render_response = requests.post(
        "https://api.creatomate.com/v1/renders",
        headers=headers,
        json=render_data
    )

    # This returns a Render ID. You can poll this ID to get the final URL 
    # when the video is finished (usually takes 5-10 seconds).
    return render_response.json()   

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)