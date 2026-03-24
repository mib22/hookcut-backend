import os, time, json, re, requests
import cloudinary, cloudinary.uploader
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

# Configuration (Ensure these are in your Render Environment Variables!)
cloudinary.config( 
  cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"), 
  api_key=os.getenv("CLOUDINARY_API_KEY"), 
  api_secret=os.getenv("CLOUDINARY_API_SECRET"),
  secure=True
)
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")

@app.post("/create-viral-edit")
async def create_viral_edit(file: UploadFile = File(...)):
    # 1. Save locally temporarily for Gemini Upload
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        buffer.write(await file.read())

    # 2. Upload to Cloudinary (for Creatomate to use later)
    upload_result = cloudinary.uploader.upload(temp_path, resource_type="video")
    video_url = upload_result.get("secure_url")

    # 3. Upload to Gemini File API (This is the fix!)
    print("Uploading to Gemini...")
    gemini_file = genai.upload_file(path=temp_path)
    
    # Wait for Gemini to process the video frames
    while gemini_file.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(2)
        gemini_file = genai.get_file(gemini_file.name)

# ... (Keep your upload code the same) ...

    # 4. Ask Gemini (Speed-Optimized Prompt)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # We add "Be concise" and "No yapping" to skip extra thinking time
    prompt = """
    TASK: Find the best 5-second viral hook in this video.
    REQUIREMENT: Return ONLY raw JSON. No markdown, no intro.
    FORMAT: { "start": 0.0, "caption": "TEXT" }
    """
    
    # Set a timeout for the actual content generation
    response = model.generate_content(
        [gemini_file, prompt],
        generation_config={"temperature": 0.1} # Lower temp = Faster, more consistent JSON
    )
    
    # Cleanup temp file
    os.remove(temp_path)

    # Extract JSON from response
    try:
        clean_json = re.search(r'\{.*\}', response.text, re.DOTALL).group()
        edit_instructions = json.loads(clean_json)
    except:
        # Fallback if AI fails
        edit_instructions = {"start": 0, "caption": "Viral Moment!"}

    # 5. Tell Creatomate to Render
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
                    "background_color": "rgba(0,0,0,0.7)"
                }
            ]
        }
    }

    headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}", "Content-Type": "application/json"}
    render_res = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=render_data)
    
    # NEW: Add a print here so you can see the Creatomate response in Render logs
    response_data = render_res.json()
    print(f"Creatomate Response: {response_data}")
    
    # Ensure we return a clean dictionary with the ID
    if isinstance(response_data, list):
        return response_data[0]
    return response_data