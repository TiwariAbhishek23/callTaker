# CallTaker / CallX

## Local build steps

1. Clone the repository
   ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```
2. Install dependencies
   ```bash
   uv sync
   ```
3. Run the agent
   ```bash
   uv run python src/agent.py dev
   ```
4. Run the fastAPI server
   ```bash
   uvicorn main:app --reload
   ```

5. Setup web interface - https://github.com/TiwariAbhishek23/callTakerSuperAdmin for admin panel

6. Setup firebase realtime databse

7. Setup web interface for call - https://github.com/livekit-examples/agent-starter-react