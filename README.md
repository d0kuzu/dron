# Drone Opportunity Analyzer

This project is designed to automatically fetch and evaluate drone (UAV) related procurement opportunities from the SAM.gov API. The application consists of a Python scraper script and a web interface (powered by FastAPI) for convenient viewing and updating of the results.

## Running with Docker (Recommended for Servers)

You can easily deploy this project to any server using Docker.

1. **Environment Setup**
   Ensure there is a `.env` file in the root directory containing your API key:
   `SAM_API_KEY=<your_api_key>`

2. **Build the Docker Image**
   ```bash
   docker build -t drone-analyzer .
   ```

3. **Run the Container**
   ```bash
   docker run -d -p 8000:8000 --env-file .env --name drone-analyzer-app drone-analyzer
   ```

4. **Open the Interface**
   Navigate in your browser to: `http://<your-server-ip>:8000`

---

## Running Locally (Without Docker)

1. **Environment Setup**
   Ensure there is a `.env` file in the root directory containing your API key:
   `SAM_API_KEY=<your_api_key>`

2. **Activate the Virtual Environment:**
   - On Windows: `.\venv\Scripts\activate`
   - On macOS/Linux: `source venv/bin/activate`

3. **Install Dependencies (if not installed):**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the Server:**
   ```bash
   uvicorn server:app --reload
   ```

5. **Open the Interface:**
   Navigate in your browser to: `http://localhost:8000`
