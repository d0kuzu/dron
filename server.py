import os
import subprocess
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.get("/")
async def root():
    # Serve index.html
    return FileResponse("static/index.html")

@app.get("/api/data")
async def get_data():
    try:
        with open("sam_matches.json", "r", encoding="utf-8") as f:
            matched = json.load(f)
        
        excluded = {"opportunities": []}
        if os.path.exists("sam_excluded.json"):
            try:
                with open("sam_excluded.json", "r", encoding="utf-8") as f:
                    excluded = json.load(f)
            except Exception:
                pass
            
        return {
            "matched": matched,
            "excluded": excluded
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/refresh")
async def refresh_data():
    api_key = os.getenv("SAM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="SAM_API_KEY is not configured in .env file.")
        
    try:
        # Run the existing main.py script
        result = subprocess.run(
            ["python", "main.py", "--api-key", api_key],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise Exception(f"Script failed: {result.stderr}")
            
        # If successful, read the newly generated data
        return await get_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
