import os
import time
import json
import re
import requests
from pathlib import Path
import shutil
import cloudinary
import cloudinary.uploader
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()
app = FastAPI(title="HookCut AI Backend", version="1.0.0")

# --- ADD THIS CORS BLOCK ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---------------------------

# Configuration
cloudinary.config( 
  cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"), 
  api_key=os.getenv("CLOUDINARY_API_KEY"), 
  api_secret=os.getenv("CLOUDINARY_API_SECRET"),
  secure=True
)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")

if not all([os.getenv("CLOUDINARY_CLOUD_NAME"), os.getenv("GOOGLE_API_KEY"), CREATOMATE_API_KEY]):
    raise RuntimeError("Missing required environment variables")

@app.get("/health")
async def health_check():
    """Health check endpoint for deployment monitoring."""
    return {"status": "healthy", "service": "hookcut-ai"}

@app.post("/create-viral-edit")
async def create_viral_edit(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., media_type="video/*", max_size=100*1024*1024)  # 100MB limit
):
    try:
        # Validate file
        if not file:
            raise HTTPException(status_code=400, detail="No video file provided")
        
        if file.size > 100 * 1024 * 1024:  # Enforce size
            raise HTTPException(status_code=413, detail="File too large (max 100MB)")

        temp_dir = Path("temp_uploads")
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"{file.filename}"
        
        # 1. Save locally
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(str(temp_path), resource_type="video")
        video_url = upload_result.get("secure_url")
        if not video_url:
            raise HTTPException(status_code=500, detail="Cloudinary upload failed")

        # 3. Upload to Gemini & wait
        print("Uploading to Gemini...")
        gemini_file = genai.upload_file(path=str(temp_path))
        
        timeout = 300  # 5 min
        start_time = time.time()
        while gemini_file.state.name == "PROCESSING":
            if time.time() - start_time > timeout:
                raise HTTPException(status_code=408, detail="Gemini processing timeout")
            print(".", end="", flush=True)
            time.sleep(2)
            gemini_file = genai.get_file(gemini_file.name)

        # 4. Generate hook instructions
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = '''
TASK: Find the best 5-second viral hook in this video.
REQUIREMENT: Return ONLY raw JSON. No markdown, no intro.
FORMAT: { "start": 0.0, "caption": "TEXT" }
        '''
        response = model.generate_content(
            [gemini_file, prompt],
            generation_config={"temperature": 0.1, "max_output_tokens": 100}
        )
        
        # Parse JSON
        try:
            clean_json = re.search(r'\{.*\}', response.text, re.DOTALL).group()
            edit_instructions = json.loads(clean_json)
            if not isinstance(edit_instructions, dict) or 'start' not in edit_instructions:
                raise ValueError("Invalid JSON format")
        except Exception as e:
            print(f"JSON parse error: {e}")
            edit_instructions = {"start": 0.0, "caption": "Epic Viral Moment!"}

        # Schedule cleanup
        background_tasks.add_task(cleanup_files, str(temp_path), gemini_file.name)

        # 5. Creatomate render
        render_data = {
            "source": {
                "output_format": "mp4",
                "elements": [
                    {
                        "type": "video",
                        "source": video_url,
                        "trim_start": edit_instructions['start'],
                        "duration": 5,
                        "smart_crop": True
                    },
                    {
                        "type": "text",
                        "text": edit_instructions['caption'],
                        "y": "80%",
                        "background_color": "rgba(0,0,0,0.7)",
                        "font_family": "Default",
                        "font_size": 48,
                        "color": "#FFFFFF"
                    }
                ]
            }
        }

        headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}", "Content-Type": "application/json"}
        render_res = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=render_data, timeout=30)
        
        if render_res.status_code != 201:
            raise HTTPException(status_code=500, detail=f"Creatomate API error: {render_res.text}")

        response_data = render_res.json()
        print(f"Creatomate render started: {response_data}")
        
        # Return first render ID
        render_id = response_data[0]['id'] if isinstance(response_data, list) else response_data.get('id')
        return JSONResponse({
            "id": render_id,
            "status": "processing",
            "message": "Viral edit rendering started!"
        })

    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

def cleanup_files(temp_path: str, gemini_file_name: str):
    """Background cleanup"""
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        try:
            genai.delete_file(gemini_file_name)
        except:
            pass  # Ignore Gemini cleanup errors
    except Exception as e:
        print(f"Cleanup error: {e}")
