# Drone Opportunity Analyzer

This project is designed to automatically fetch and evaluate drone (UAV) related procurement opportunities from the SAM.gov API. The application consists of a Python scraper script and a web interface (powered by FastAPI) for convenient viewing and updating of the results.

### Launch Instructions

To run the project, please execute the following steps in your terminal from the project's root directory:

1. **Environment Setup**
   Ensure there is a `.env` file in the root directory containing your API key:
   `SAM_API_KEY=<your_api_key>`

2. **Activate the Virtual Environment:**
   - On Windows: `.\venv\Scripts\activate`
   - On macOS/Linux: `source venv/bin/activate`

3. **Start the Server:**
   Run the following command:
   ```
   uvicorn server:app --reload
   ```

4. **Open the Interface:**
   Navigate in your browser to: `http://localhost:8000`
