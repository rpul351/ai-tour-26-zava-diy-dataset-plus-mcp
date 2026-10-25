"""
Web Interface for Azure AI Agent Chat

This web application provides a user interface for interacting with the AI agent
through REST API calls to the agent service.

To run: python web_app.py
Web interface available at: http://127.0.0.1:8005
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import AsyncGenerator, Dict, List

# Add workshop folder to path to import shared modules
sys.path.append(str(Path(__file__).parent.parent / "workshop"))

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import chat_store
import roles
from charts import CHART_DIR, valid_chart_name
from exports import EXPORT_DIR, media_type, valid_export_name

# Configure logging
logging.basicConfig(level=logging.ERROR)

# Agent service configuration
AGENT_SERVICE_URL = "http://127.0.0.1:8006"


class FreshStaticFiles(StaticFiles):
    """Static files a browser must check with the server each time, so a new page never runs an old script."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class WebApp:
    """Handles all web interface functionality for the AI Agent Chat application."""
    
    def __init__(self, app: FastAPI) -> None:
        """Initialize the web interface with FastAPI app."""
        self.app = app
        self.chat_sessions: Dict[str, List[Dict]] = {}
        
        self._setup_routes()
        self._setup_static_files()
    
    def _setup_static_files(self) -> None:
        """Setup static file serving."""
        static_dir = Path(__file__).parent.parent.parent / "shared" / "static"
        self.app.mount("/static", FreshStaticFiles(directory=str(static_dir)), name="static")
    
    def _setup_routes(self) -> None:
        """Setup all web routes."""
        self.app.get("/", response_class=HTMLResponse)(self.get_chat_page)
        self.app.get("/favicon.ico", response_class=FileResponse)(self.get_favicon)
        self.app.post("/upload")(self.upload_file)
        self.app.get("/chat/stream")(self.stream_chat)
        self.app.get("/files/{filename}")(self.serve_file)
        self.app.get("/charts/{name}")(self.serve_chart)
        self.app.get("/exports/{name}")(self.serve_export)
        self.app.get("/health")(self.health_check)
        self.app.get("/api/me")(self.me)
        self.app.get("/api/chats")(self.list_chats)
        self.app.get("/api/chats/{chat_id}")(self.read_chat)
        self.app.delete("/api/chats/{chat_id}")(self.remove_chat)
    
    async def get_chat_page(self) -> HTMLResponse:
        """Serve the chat HTML page."""
        static_dir = Path(__file__).parent.parent.parent / "shared" / "static"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        # A version in each asset address changes whenever a file changes, so no browser keeps an old script or style sheet.
        version = int(max(f.stat().st_mtime for f in static_dir.iterdir() if f.suffix in (".js", ".css", ".html")))
        html = re.sub(r'((?:src|href)="/static/[^"?]+)"', rf'\1?v={version}"', html)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
    
    async def get_favicon(self) -> FileResponse:
        """Serve the favicon.ico file."""
        favicon_path = Path(__file__).parent.parent.parent / "shared" / "static" / "favicon.ico"
        return FileResponse(favicon_path, media_type="image/x-icon")
    
    async def upload_file(self, file: UploadFile, message: str = Form(None)) -> Dict:
        """Handle file upload and extract text content."""
        try:
            # Check file size (10MB limit)
            content = await file.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="File too large (max 10MB)")

            # Extract text based on file type
            file_text = ""
            file_extension = (
                file.filename.lower().split(".")[-1] if file.filename and "." in file.filename else ""
            )

            if file_extension in ["txt", "md"]:
                file_text = content.decode("utf-8")
            elif file_extension in ["pdf"]:
                file_text = f"[PDF file: {file.filename}]"  # Could integrate PDF parsing
            elif file_extension in ["doc", "docx"]:
                file_text = f"[Word document: {file.filename}]"  # Could integrate Word parsing
            else:
                file_text = f"[Uploaded file: {file.filename}]"

            # Prepare the message with file content
            if message:
                combined_message = f"{message}\n\nAttached file content:\n{file_text}"
            else:
                combined_message = f"Please analyze this file:\n\n{file_text}"

            return {"content": combined_message, "filename": file.filename}

        except Exception as e:
            return {"error": f"Error processing file: {e!s}"}
    
    @staticmethod
    def _private(payload, status_code: int = 200) -> JSONResponse:
        """Saved chats are personal, so nothing here may be cached by the browser or a proxy."""
        return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})

    async def me(self, request: Request) -> JSONResponse:
        """Who is signed in, with their role and the stores they can see."""
        person = roles.describe(getattr(request.state, "zava_user", None))
        if person is None:
            return self._private({"error": "Not signed in."}, 401)
        return self._private(person)

    async def list_chats(self, request: Request, q: str = "") -> JSONResponse:
        user = getattr(request.state, "zava_user", None)
        return self._private({"chats": await asyncio.to_thread(chat_store.list_chats, user, q)})

    async def read_chat(self, request: Request, chat_id: str) -> JSONResponse:
        user = getattr(request.state, "zava_user", None)
        chat = await asyncio.to_thread(chat_store.get_chat, user, chat_id) if chat_store.valid_id(chat_id) else None
        return self._private(chat, 200) if chat else self._private({"error": "Chat not found."}, 404)

    async def remove_chat(self, request: Request, chat_id: str) -> JSONResponse:
        user = getattr(request.state, "zava_user", None)
        removed = await asyncio.to_thread(chat_store.delete_chat, user, chat_id) if chat_store.valid_id(chat_id) else False
        return self._private({"ok": True}) if removed else self._private({"error": "Chat not found."}, 404)

    async def stream_chat(self, request: Request, message: str = "", session_id: str = "", store: str = "") -> StreamingResponse:
        """Stream chat responses by proxying to the agent service."""
        if not message.strip():
            return StreamingResponse(
                iter([f"data: {json.dumps({'error': 'Empty message'})}\n\n"]),
                media_type="text/event-stream",
            )

        # Each browser tab sends its own id so people do not share one conversation.
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
            session_id = "default"
        if session_id not in self.chat_sessions:
            self.chat_sessions[session_id] = []

        # Add user message to session
        self.chat_sessions[session_id].append({"role": "user", "content": message})
        user = getattr(request.state, "zava_user", None)
        if user and session_id != "default" and not await asyncio.to_thread(chat_store.ensure_chat, user, session_id):
            return StreamingResponse(
                iter([f"data: {json.dumps({'error': 'That chat is not available.'})}\n\n"]), media_type="text/event-stream"
            )

        return StreamingResponse(
            self._generate_stream(message, session_id, getattr(request.state, "zava_user", None), store[:100] or None),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache", 
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Content-Encoding": "identity"
            },
        )
    
    async def _generate_stream(
        self, message: str, session_id: str, user: str | None = None, store: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response by proxying to agent service."""
        saving = bool(user) and session_id != "default"
        try:
            earlier = await asyncio.to_thread(chat_store.recent_messages, user, session_id) if saving else []
            if saving:
                await asyncio.to_thread(chat_store.add_message, user, session_id, "user", message)
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Make request to agent service. The saved messages let the agent pick the conversation up again after a restart.
                request_data = {
                    "message": message,
                    "session_id": session_id,
                    "store": store,
                    "history": earlier,
                }
                
                async with client.stream(
                    "POST",
                    f"{AGENT_SERVICE_URL}/chat/stream",
                    json=request_data,
                    headers={"Accept": "text/event-stream", **({"X-Zava-User": user} if user else {})}
                ) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Agent service error: {response.status_code}'})}\n\n"
                        return
                    
                    assistant_message = ""
                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            # Parse and forward each chunk
                            lines = chunk.strip().split('\n')
                            for line in lines:
                                if line.startswith('data: '):
                                    data_str = line[6:]  # Remove 'data: ' prefix
                                    try:
                                        data = json.loads(data_str)
                                        
                                        # Convert agent service response format to web format
                                        if data.get("tool"):
                                            yield f"data: {json.dumps({'tool': data['tool']})}\n\n"
                                        elif data.get("status"):
                                            yield f"data: {json.dumps({'status': data['status']})}\n\n"
                                        elif data.get("content"):
                                            assistant_message += data["content"]
                                            yield f"data: {json.dumps({'content': data['content']})}\n\n"
                                        elif data.get("file_info"):
                                            yield f"data: {json.dumps({'file': data['file_info']})}\n\n"
                                        elif data.get("error"):
                                            yield f"data: {json.dumps({'error': data['error']})}\n\n"
                                        elif data.get("done"):
                                            # Agent service signals completion
                                            break
                                    except json.JSONDecodeError:
                                        # Skip malformed JSON
                                        continue
                    
                    # Add complete message to session
                    if assistant_message:
                        self.chat_sessions[session_id].append({
                            "role": "assistant", 
                            "content": assistant_message
                        })
                    if assistant_message and saving:
                        await asyncio.to_thread(chat_store.add_message, user, session_id, "assistant", assistant_message)

            # Send completion signal
            yield "data: [DONE]\n\n"

        except httpx.RequestError as e:
            yield f"data: {json.dumps({'error': f'Connection error to agent service: {e!s}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Streaming error: {e!s}'})}\n\n"
    
    async def serve_chart(self, name: str) -> FileResponse:
        """Serve a chart the agent drew. Names are random, and only a fixed pattern is accepted."""
        path = CHART_DIR / name
        if not valid_chart_name(name) or not path.is_file():
            raise HTTPException(status_code=404, detail="Chart not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    async def serve_export(self, name: str) -> FileResponse:
        """Serve a CSV or PDF the agent wrote, as a download. Names are random, and only a fixed pattern is accepted."""
        path = EXPORT_DIR / name
        if not valid_export_name(name) or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(
            path,
            media_type=media_type(name),
            filename=f"zava_{name}",
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    async def serve_file(self, filename: str) -> FileResponse:
        """Proxy file serving to agent service or serve locally."""
        try:
            # Try to proxy to agent service first
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{AGENT_SERVICE_URL}/files/{filename}")
                if response.status_code == 200:
                    # Save file temporarily and serve it
                    temp_file = Path("/tmp") / filename
                    with temp_file.open("wb") as f:
                        f.write(response.content)
                    return FileResponse(path=str(temp_file))
        except Exception:
            pass
        
        # Fallback to local file serving
        files_dir = Path() / "images"
        file_path = files_dir / filename
        
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        
        # Security check: ensure the file is within the files directory
        try:
            file_path.resolve().relative_to(files_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Access denied") from exc
        
        return FileResponse(path=str(file_path))
    
    async def health_check(self) -> Dict:
        """Check health of web app and agent service."""
        web_status = {"status": "healthy", "service": "web_interface"}
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{AGENT_SERVICE_URL}/health")
                if response.status_code == 200:
                    agent_status = response.json()
                    return {
                        **web_status,
                        "agent_service": agent_status
                    }
                return {
                    **web_status,
                    "agent_service": {"status": "error", "code": response.status_code}
                }
        except Exception as e:
            return {
                **web_status,
                "agent_service": {"status": "error", "error": str(e)}
            }


# FastAPI app
app = FastAPI(title="Azure AI Agent Web Interface")

# Initialize web app
web_app = WebApp(app)

from temp_access import install_temp_access  # TEMP ACCESS: remove before deploying to Azure
install_temp_access(app)  # TEMP ACCESS: remove before deploying to Azure


if __name__ == "__main__":
    import uvicorn

    print("Starting web interface...")
    print(f"Agent service URL: {AGENT_SERVICE_URL}")
    uvicorn.run(app, host="127.0.0.1", port=8005)
