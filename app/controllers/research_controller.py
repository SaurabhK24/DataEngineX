import os
import uuid
import time
import base64
import json
import requests
import httpx
import PyPDF2
from io import BytesIO
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import HTTPException
from llama_api_client import LlamaAPIClient
from openai import OpenAI


from app.models.research_models import *
from app.models.paper import PaperResponse
from app.utils.config import Config


# Load API key from environment variable; this should be set in advance
LLAMA_API_KEY = os.environ.get('LLAMA_API_KEY')



# Define the base URL
BASE_URL = "https://api.llama.com/v1"


client = OpenAI(
    api_key=os.environ.get("LLAMA_API_KEY"), 
    base_url="https://api.llama.com/v1/chat/completions"
) if os.environ.get("LLAMA_API_KEY") else None

class ResearchController:
    """Controller for research platform functionality - NotebookLM competitor"""
    
    def __init__(self):
        # Initialize Llama API client
        self.llama_client = LlamaAPIClient(
            api_key=LLAMA_API_KEY,
            base_url=BASE_URL,
        ) if os.getenv("LLAMA_API_KEY") else None
        
        self.supabase_url = Config.SUPABASE_URL
        self.supabase_key = Config.SUPABASE_KEY
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

    # ========================================================================
    # PAPER MANAGEMENT
    # ========================================================================
    
    async def upload_paper(self, request: PaperUploadRequest, user: UserContext) -> PaperProcessResponse:
        """Upload and process a PDF paper"""
        start_time = time.time()
        
        try:

            print(f"📄 Processing uploaded paper: {request.file_name}")
            #print("CALLING EXTRACT_PDF_TEXT FUNCTION from UPLOAD PAPER CONTROLLER")
            # Extract text from PDF
            full_text = self._extract_pdf_text(request.file_content)

            #print("Extracted text from the pdf EXTRACT_PDF_TEXT FUNCTION END from UPLOAD PAPER CONTROLLER!")
            #print(full_text)
            
            # Use Llama to extract/enhance metadata
            #print("-------------------------------------------")
            #print("Calling EXTRACT_METADATA_WITH_LLAMA FUNCTION from UPLOAD PAPER CONTROLLER")
            metadata = await self._extract_metadata_with_llama(
                full_text, request.file_name, request.title, request.authors
            )
            #print("EXTRACT_METADATA_WITH_LLAMA FUNCTION END from UPLOAD PAPER CONTROLLER!")
            #print("-------------------------------------------")
            # Save PDF to local uploads directory so it can be served back
            paper_uuid = str(uuid.uuid4())
            file_path   = os.path.join("uploads", f"{paper_uuid}.pdf")
            try:
                with open(file_path, "wb") as f:
                    f.write(request.file_content)
            except Exception as e:
                print(f"Failed to persist uploaded PDF: {e}")
                file_path = None

            file_url = f"/files/{paper_uuid}.pdf" if file_path else None

            # Create paper record
            paper_data = {
                "id": paper_uuid,
                "paper_id": f"upload_{paper_uuid[:8]}",
                "title": metadata["title"],
                "authors": metadata["authors"],
                "abstract": metadata["abstract"],
                "year": metadata["year"],
                "topics": metadata["topics"],
                "pdf_url": file_url or f"uploaded://{paper_uuid}",
                "pdf_file_path": file_path,
                "full_text": full_text,
                "processing_status": "completed",
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            #print("This is the paper data", paper_data)
            # Store in Supabase
            await self._store_paper(paper_data)

            print("Upload to supabase complete")
            
            # Generate initial analysis
            analysis_preview = await self._generate_quick_analysis(full_text)
            
            processing_time = time.time() - start_time
            
            saved_paper = SavedPaper(
                id=UUID(paper_uuid),
                paper_id=paper_data["paper_id"],
                title=paper_data["title"],
                authors=paper_data["authors"],
                abstract=paper_data["abstract"],
                year=paper_data["year"],
                topics=paper_data["topics"],
                pdf_url=file_url,
                full_text=full_text,
                processing_status="completed",
                created_at=paper_data["created_at"],
                updated_at=paper_data["updated_at"]
            )
            
            return PaperProcessResponse(
                success=True,
                message=f"📚 Successfully processed '{metadata['title']}'",
                paper=saved_paper,
                analysis_preview=analysis_preview,
                processing_time=processing_time
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process paper: {str(e)}")
    
    async def save_arxiv_paper(self, paper: PaperResponse, user: UserContext) -> PaperProcessResponse:
        """Save an ArXiv paper to research library"""
        try:
            # Download PDF and extract text
            pdf_content = await self._download_pdf(paper.url)
            full_text = self._extract_pdf_text(pdf_content)
            
            # Create paper record
            paper_uuid = str(uuid.uuid4())
            paper_data = {
                "id": paper_uuid,
                "paper_id": paper.id,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "year": paper.year,
                "topics": paper.topics,
                "pdf_url": paper.url,
                "full_text": full_text,
                "processing_status": "completed",
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            await self._store_paper(paper_data)
            
            # Generate initial analysis
            analysis_preview = await self._generate_quick_analysis(full_text)
            
            saved_paper = SavedPaper(
                id=UUID(paper_uuid),
                paper_id=paper.id,
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                year=paper.year,
                topics=paper.topics,
                pdf_url=paper.url,
                full_text=full_text,
                processing_status="completed",
                created_at=paper_data["created_at"],
                updated_at=paper_data["updated_at"]
            )
            
            return PaperProcessResponse(
                success=True,
                message=f"📚 Added '{paper.title}' to your research library",
                paper=saved_paper,
                analysis_preview=analysis_preview,
                processing_time=2.0
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save ArXiv paper: {str(e)}")
    
    async def get_library(self, user: UserContext) -> List[SavedPaper]:
        """Get user's research library"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.supabase_url}/rest/v1/papers",
                    headers=self._get_headers(),
                    params={
                        "user_id": f"eq.{str(user.user_id)}",
                        "order": "created_at.desc"
                    }
                )
                response.raise_for_status()
                papers_data = response.json()
                
                return [self._convert_to_saved_paper(paper) for paper in papers_data]
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get library: {str(e)}")
    
    # ========================================================================
    # ANNOTATIONS & HIGHLIGHTS
    # ========================================================================
    
    async def create_highlight(self, request: CreateHighlightRequest, user: UserContext) -> HighlightResponse:
        """Create a highlight in a paper"""
        try:
            highlight_id = str(uuid.uuid4())
            highlight_data = {
                "id": highlight_id,
                "paper_id": str(request.paper_id),
                "highlight_text": request.text,
                "page_number": request.page_number,
                "position": request.position,
                "color": request.color,
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.supabase_url}/rest/v1/highlights",
                    headers=self._get_headers(),
                    json=highlight_data
                )
                response.raise_for_status()
            
            return HighlightResponse(
                id=UUID(highlight_id),
                paper_id=request.paper_id,
                text=request.text,
                page_number=request.page_number,
                position=request.position,
                color=request.color,
                created_at=highlight_data["created_at"]
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create highlight: {str(e)}")
    
    async def create_annotation(self, request: CreateAnnotationRequest, user: UserContext) -> AnnotationResponse:
        """Create an annotation"""
        try:
            annotation_id = str(uuid.uuid4())
            annotation_data = {
                "id": annotation_id,
                "paper_id": str(request.paper_id),
                "highlight_id": str(request.highlight_id) if request.highlight_id else None,
                "content": request.content,
                "annotation_type": request.annotation_type,
                "page_number": request.page_number,
                "position": request.position,
                "tags": request.tags,
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.supabase_url}/rest/v1/annotations",
                    headers=self._get_headers(),
                    json=annotation_data
                )
                response.raise_for_status()
            
            return AnnotationResponse(
                id=UUID(annotation_id),
                paper_id=request.paper_id,
                highlight_id=request.highlight_id,
                content=request.content,
                annotation_type=request.annotation_type,
                page_number=request.page_number,
                position=request.position,
                tags=request.tags,
                created_at=annotation_data["created_at"],
                updated_at=annotation_data["updated_at"]
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create annotation: {str(e)}")
    
    # ========================================================================
    # CHAT WITH PAPERS (LLAMA 4)
    # ========================================================================
    
    async def create_chat_session(self, request: ChatSessionRequest, user: UserContext) -> ChatSessionResponse:
        """Create a chat session with a paper or collection"""
        try:
            session_id = str(uuid.uuid4())
            session_data = {
                "id": session_id,
                "paper_id": str(request.paper_id) if request.paper_id else None,
                "session_name": request.session_name or "Chat Session",
                "session_type": request.session_type,
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.supabase_url}/rest/v1/chat_sessions",
                    headers=self._get_headers(),
                    json=session_data
                )
                response.raise_for_status()
            
            return ChatSessionResponse(
                id=UUID(session_id),
                paper_id=request.paper_id,
                session_name=session_data["session_name"],
                session_type=request.session_type,
                messages_count=0,
                created_at=session_data["created_at"],
                updated_at=session_data["updated_at"]
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create chat session: {str(e)}")
    
    async def send_chat_message(self, request: ChatMessageRequest, user: UserContext) -> ChatMessageResponse:
        """Send a message and get Llama 4 response"""
        try:
            if not self.llama_client:
                raise HTTPException(status_code=400, detail="Llama API not configured")
            
            # Get session context
            session_context = await self._get_session_context(request.session_id, user)
            
            # Build context for Llama
            context = await self._build_chat_context(session_context, request.message)
            
            # Get Llama response
            llama_response = await self._get_llama_chat_response(context, request.message)
            
            # Store user message
            user_msg_id = await self._store_chat_message(
                session_id=request.session_id,
                role="user",
                content=request.message,
                user=user
            )
            
            # Store assistant response
            assistant_msg_id = await self._store_chat_message(
                session_id=request.session_id,
                role="assistant", 
                content=llama_response["content"],
                sources=llama_response.get("sources", []),
                user=user
            )
            
            return ChatMessageResponse(
                id=UUID(assistant_msg_id),
                session_id=request.session_id,
                role="assistant",
                content=llama_response["content"],
                sources=llama_response.get("sources", []),
                created_at=datetime.now(timezone.utc).isoformat()
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to send chat message: {str(e)}")
    
    # ========================================================================
    # ANALYSIS & INSIGHTS
    # ========================================================================
    
    async def analyze_paper(self, request: AnalysisRequest, user: UserContext) -> AnalysisResponse:
        """Analyze a paper using Llama 4"""
        try:
            if not self.llama_client:
                raise HTTPException(status_code=400, detail="Llama API not configured")
            
            # Get paper content
            paper = await self._get_paper(request.paper_id, user)
            
            # Generate analysis with Llama
            analysis = await self._generate_paper_analysis(
                paper["full_text"], 
                request.analysis_type,
                request.focus_areas
            )
            
            # Store analysis
            analysis_id = str(uuid.uuid4())
            analysis_data = {
                "id": analysis_id,
                "paper_id": str(request.paper_id),
                "analysis_type": request.analysis_type,
                "content": analysis["content"],
                "insights": analysis["insights"],
                "key_quotes": analysis["key_quotes"],
                "related_concepts": analysis["related_concepts"],
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            # You would store this in an analyses table
            
            return AnalysisResponse(
                id=UUID(analysis_id),
                paper_id=request.paper_id,
                analysis_type=request.analysis_type,
                content=analysis["content"],
                insights=analysis["insights"],
                key_quotes=analysis["key_quotes"],
                related_concepts=analysis["related_concepts"],
                created_at=analysis_data["created_at"]
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to analyze paper: {str(e)}")
    
    # ========================================================================
    # SEARCH & DISCOVERY
    # ========================================================================
    
    async def search_library(self, request: SearchRequest, user: UserContext) -> SearchResponse:
        """Search within user's research library"""
        start_time = time.time()
        
        try:
            results = []
            
            # Search papers
            if "papers" in request.search_in:
                paper_results = await self._search_papers(request.query, user, request.limit)
                results.extend(paper_results)
            
            # Search annotations
            if "annotations" in request.search_in:
                annotation_results = await self._search_annotations(request.query, user, request.limit)
                results.extend(annotation_results)
            
            # Search highlights
            if "highlights" in request.search_in:
                highlight_results = await self._search_highlights(request.query, user, request.limit)
                results.extend(highlight_results)
            
            # Sort by relevance (you'd implement proper scoring)
            results.sort(key=lambda x: x.relevance_score, reverse=True)
            
            search_time = time.time() - start_time
            
            return SearchResponse(
                query=request.query,
                total_results=len(results),
                results=results[:request.limit],
                search_time=search_time
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================


    def chat_completion(self, messages, model="Llama-4-Maverick-17B-128E-Instruct-FP8", max_tokens=256):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLAMA_API_KEY}"
        }

        payload = {
            "messages": messages,
            "model": model,
            "max_tokens": max_tokens,
            "stream": False
        }    
        response = requests.post(
            f"{BASE_URL}/chat/completions", 
            headers=headers, 
            json=payload
        )

        return response.json()
        
    def _extract_pdf_text(self, pdf_content: bytes) -> str:
        """Extract text from PDF using PyPDF2"""        
        #print("STARTING EXTRACT_PDF_TEXT FUNCTION! INSIDE EXTRACT PDF TEXT FUNCTION")
        try:
            pdf_file = BytesIO(pdf_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            #print("END OF EXTRACT PDF TEXT FUNCTION!")
            return text.strip()
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            return ""
    
    async def _extract_metadata_with_llama(self, full_text: str, filename: str, title: Optional[str], authors: Optional[List[str]]) -> dict:
        """Extract metadata using Llama 4"""
        
        # ------------------------------------------------------------------
        # Clean implementation: use the OpenAI-compatible client against the
        # Llama 4 endpoint to extract structured metadata.
        # ------------------------------------------------------------------

        prompt = f"""
        Extract metadata from the following scientific paper.
        Return ONLY valid JSON with keys: title, authors (array), abstract,
        year (number), topics (array of 5-8 keywords).

        Known info: Title=\"{title}\", Authors={authors}

        Paper text (first 3000 chars):
        {full_text[:3000]}
        """

        try:
            response = client.chat.completions.create(
                model="Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0
            )

            content = response.choices[0].message.content.strip()

            print("This is the content from the llama 4 function", content)

            # Attempt to parse JSON strictly; if model wrapped the JSON in
            # ``` or text, try to locate the first \{ and last \} pair.
            try:
                metadata = json.loads(content)
            except json.JSONDecodeError:
                try:
                    start = content.index("{")
                    end = content.rindex("}") + 1
                    metadata = json.loads(content[start:end])
                except Exception:
                    raise ValueError("Model did not return valid JSON")

            return {
                "title": metadata.get("title", title or filename),
                "authors": metadata.get("authors", authors or []),
                "abstract": metadata.get("abstract"),
                "year": metadata.get("year"),
                "topics": metadata.get("topics", [])
            }

        except Exception as e:
            print(f"Llama metadata extraction failed: {e}")
            return {
                "title": title or filename.replace(".pdf", ""),
                "authors": authors or [],
                "abstract": None,
                "year": None,
                "topics": []
            }
    
    async def _generate_quick_analysis(self, full_text: str) -> Optional[str]:
        """Generate a quick analysis preview"""
        if not self.llama_client or not full_text:
            return None
        
        try:
            prompt = f"""
            Provide a 3-sentence analysis of this research paper's key contributions and significance.
            
            Paper text (first 2000 chars):
            {full_text[:2000]}
            """
            
            response = self.llama_client.chat.completions.create(
                model="Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[{"role": "user", "content": prompt}]
            )
            
            return self._extract_llama_content(response)
            
        except Exception as e:
            print(f"Quick analysis failed: {e}")
            return None
    
    def _extract_llama_content(self, response) -> str:
        """Extract content from Llama response"""
        if hasattr(response, "completion_message"):
            return response.completion_message.content.text.strip()
        elif hasattr(response, "choices"):
            return response.choices[0].message.content.strip()
        else:
            return str(response).strip()
    
    def _get_headers(self) -> dict:
        """Get Supabase headers"""
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json"
        }
    
    async def _store_paper(self, paper_data: dict):
        """Insert or update a paper row in Supabase (handles duplicates)."""
        #print("-----------------------------------------")
        #print("entering store paper function")
        
        # Helper to recursively remove null bytes from strings
        def _clean_nulls(value):
            if isinstance(value, str):
                return value.replace("\x00", "")
            if isinstance(value, list):
                return [_clean_nulls(v) for v in value]
            if isinstance(value, dict):
                return {k: _clean_nulls(v) for k, v in value.items()}
            return value

        # Ensure JSONB fields are proper types
        paper_data["authors"] = paper_data.get("authors", [])
        paper_data["topics"] = paper_data.get("topics", [])

        # Strip problematic null bytes that Postgres rejects (code 22P05)
        paper_data = {k: _clean_nulls(v) for k, v in paper_data.items()}

        headers = self._get_headers()
        
        #print("Got headers: ", headers)
        # Ask Supabase to merge duplicates on (user_id,paper_id) unique constraint
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.supabase_url}/rest/v1/papers",
                headers=headers,
                json=paper_data,
                timeout=30
            )

            if resp.status_code >= 400:
                # Log response body for easier debugging then raise
                print(f"Supabase insert failed: {resp.status_code} {resp.text}")
                resp.raise_for_status()
    
    def _convert_to_saved_paper(self, paper_data: dict) -> SavedPaper:
        """Convert database paper to SavedPaper model"""
        return SavedPaper(
            id=UUID(paper_data["id"]),
            paper_id=paper_data["paper_id"],
            title=paper_data["title"],
            authors=paper_data["authors"],
            abstract=paper_data.get("abstract"),
            year=paper_data.get("year"),
            topics=paper_data.get("topics", []),
            pdf_url=paper_data["pdf_url"],
            full_text=paper_data.get("full_text"),
            processing_status=paper_data.get("processing_status", "completed"),
            created_at=paper_data["created_at"],
            updated_at=paper_data.get("updated_at", paper_data["created_at"])
        )
    
    # Additional helper methods would be implemented here...
    async def _download_pdf(self, url: str) -> bytes:
        """Download PDF from URL"""
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
    
    async def _get_session_context(self, session_id: UUID, user: UserContext) -> dict:
        """Get chat session context"""
        try:
            async with httpx.AsyncClient() as client:
                # Get session details
                session_response = await client.get(
                    f"{self.supabase_url}/rest/v1/chat_sessions",
                    headers=self._get_headers(),
                    params={
                        "id": f"eq.{session_id}",
                        "user_id": f"eq.{user.user_id}"
                    }
                )
                session_response.raise_for_status()
                sessions = session_response.json()
                
                if not sessions:
                    return {}
                
                session = sessions[0]
                context = {"session": session}
                
                # Get paper content if it's a paper session
                if session.get("paper_id"):
                    paper_response = await client.get(
                        f"{self.supabase_url}/rest/v1/papers",
                        headers=self._get_headers(),
                        params={
                            "id": f"eq.{session['paper_id']}",
                            "user_id": f"eq.{user.user_id}"
                        }
                    )
                    paper_response.raise_for_status()
                    papers = paper_response.json()
                    if papers:
                        context["paper"] = papers[0]
                
                # Get recent messages for context
                messages_response = await client.get(
                    f"{self.supabase_url}/rest/v1/chat_messages",
                    headers=self._get_headers(),
                    params={
                        "session_id": f"eq.{session_id}",
                        "order": "created_at.desc",
                        "limit": "10"
                    }
                )
                messages_response.raise_for_status()
                context["recent_messages"] = messages_response.json()
                
                return context
                
        except Exception as e:
            print(f"Error getting session context: {e}")
            return {}
    
    async def _build_chat_context(self, session_context: dict, message: str) -> str:
        """Build context for Llama chat"""
        context_parts = []
        
        # Add paper content if available
        if "paper" in session_context:
            paper = session_context["paper"]
            context_parts.append(f"PAPER CONTEXT:")
            context_parts.append(f"Title: {paper.get('title', 'Unknown')}")
            context_parts.append(f"Authors: {', '.join(paper.get('authors', []))}")
            if paper.get('abstract'):
                context_parts.append(f"Abstract: {paper['abstract']}")
            
            # Add paper text (truncated)
            if paper.get('full_text'):
                text = paper['full_text'][:4000]  # Limit context size
                context_parts.append(f"Paper Content (excerpt): {text}")
        
        # Add recent conversation
        if "recent_messages" in session_context and session_context["recent_messages"]:
            context_parts.append("\nRECENT CONVERSATION:")
            for msg in reversed(session_context["recent_messages"][-5:]):  # Last 5 messages
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")
        
        # Add current message
        context_parts.append(f"\nCURRENT USER MESSAGE: {message}")
        
        return "\n".join(context_parts)
    
    async def _get_llama_chat_response(self, context: str, message: str) -> dict:
        """Get Llama chat response"""
        if not self.llama_client:
            return {"content": "Chat functionality requires Llama API key", "sources": []}
        
        try:
            prompt = f"""You are a research assistant helping users understand academic papers. 
            
            {context}
            
            Provide a helpful, detailed response to the user's question. If citing specific information, 
            mention where it comes from in the paper. Be accurate and academic in tone."""
            
            response = self.llama_client.chat.completions.create(
                model="Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.7
            )
            
            content = self._extract_llama_content(response)
            
            # Simple source detection (could be improved)
            sources = []
            if "paper" in context.lower() and any(word in content.lower() for word in ["according to", "the paper", "authors"]):
                sources.append({"type": "paper", "reference": "Current paper"})
            
            return {"content": content, "sources": sources}
            
        except Exception as e:
            print(f"Llama chat response failed: {e}")
            return {"content": f"Sorry, I encountered an error: {str(e)}", "sources": []}
    
    async def _store_chat_message(self, session_id: UUID, role: str, content: str, user: UserContext, sources: List = None) -> str:
        """Store chat message"""
        try:
            message_id = str(uuid.uuid4())
            message_data = {
                "id": message_id,
                "session_id": str(session_id),
                "role": role,
                "content": content,
                "sources": sources or [],
                "user_id": str(user.user_id),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.supabase_url}/rest/v1/chat_messages",
                    headers=self._get_headers(),
                    json=message_data
                )
                response.raise_for_status()
            
            return message_id
            
        except Exception as e:
            print(f"Error storing chat message: {e}")
            return str(uuid.uuid4())  # Return dummy ID on failure
    
    async def _get_paper(self, paper_id: UUID, user: UserContext) -> dict:
        """Get paper by ID"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.supabase_url}/rest/v1/papers",
                    headers=self._get_headers(),
                    params={
                        "id": f"eq.{paper_id}",
                        "user_id": f"eq.{user.user_id}"
                    }
                )
                response.raise_for_status()
                papers = response.json()
                
                return papers[0] if papers else {}
                
        except Exception as e:
            print(f"Error getting paper: {e}")
            return {}
    
    async def _generate_paper_analysis(self, full_text: str, analysis_type: str, focus_areas: List[str]) -> dict:
        """Generate paper analysis using Llama"""
        if not self.llama_client or not full_text:
            return {
                "content": "Analysis requires Llama API key and paper content",
                "insights": [],
                "key_quotes": [],
                "related_concepts": []
            }
        
        try:
            focus_text = ", ".join(focus_areas) if focus_areas else "general analysis"
            
            prompt = f"""
            Analyze this research paper with focus on: {focus_text}
            
            Analysis type: {analysis_type}
            
            {full_text}
            
            Provide:
            1. Main findings and contributions
            2. Key insights and implications
            3. Important quotes or statements
            4. Related concepts and topics
            
            Format as JSON with fields: content, insights, key_quotes, related_concepts
            """
            
            response = self.llama_client.chat.completions.create(
                model="Llama-4-Maverick-17B-128E-Instruct-FP8",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.5
            )
            
            #print("This is the response from the llama client", response)
            content = self._extract_llama_content(response)
            
            # Try to parse as JSON, fallback to simple structure
            try:
                analysis = json.loads(content)
                return {
                    "content": analysis.get("content", content),
                    "insights": analysis.get("insights", []),
                    "key_quotes": analysis.get("key_quotes", []),
                    "related_concepts": analysis.get("related_concepts", [])
                }
            except json.JSONDecodeError:
                return {
                    "content": content,
                    "insights": ["Detailed analysis generated"],
                    "key_quotes": [],
                    "related_concepts": focus_areas
                }
            
        except Exception as e:
            print(f"Analysis generation failed: {e}")
            return {
                "content": f"Analysis failed: {str(e)}",
                "insights": [],
                "key_quotes": [],
                "related_concepts": []
            }
    
    async def _search_papers(self, query: str, user: UserContext, limit: int) -> List[SearchResult]:
        """Search papers"""
        try:
            async with httpx.AsyncClient() as client:
                # Simple text search in title, abstract, and full_text
                response = await client.get(
                    f"{self.supabase_url}/rest/v1/papers",
                    headers=self._get_headers(),
                    params={
                        "user_id": f"eq.{user.user_id}",
                        "or": f"(title.ilike.%{query}%,abstract.ilike.%{query}%,full_text.ilike.%{query}%)",
                        "limit": str(limit),
                        "order": "created_at.desc"
                    }
                )
                response.raise_for_status()
                papers = response.json()
                
                results = []
                for paper in papers:
                    # Simple relevance scoring
                    relevance = 0.5
                    if query.lower() in paper.get('title', '').lower():
                        relevance += 0.3
                    if query.lower() in paper.get('abstract', '').lower():
                        relevance += 0.2
                    
                    results.append(SearchResult(
                        type="paper",
                        id=paper["id"],
                        title=paper.get("title", "Untitled"),
                        content=paper.get("abstract", "")[:200] + "..." if paper.get("abstract") else "",
                        relevance_score=relevance,
                        source="library"
                    ))
                
                return sorted(results, key=lambda x: x.relevance_score, reverse=True)
                
        except Exception as e:
            print(f"Error searching papers: {e}")
            return []
    
    async def _search_annotations(self, query: str, user: UserContext, limit: int) -> List[SearchResult]:
        """Search annotations"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.supabase_url}/rest/v1/annotations",
                    headers=self._get_headers(),
                    params={
                        "user_id": f"eq.{user.user_id}",
                        "annotation_text.ilike": f"%{query}%",
                        "limit": str(limit),
                        "order": "created_at.desc"
                    }
                )
                response.raise_for_status()
                annotations = response.json()
                
                results = []
                for annotation in annotations:
                    results.append(SearchResult(
                        type="annotation",
                        id=annotation["id"],
                        title=f"Annotation: {annotation.get('annotation_text', '')[:50]}...",
                        content=annotation.get('annotation_text', ''),
                        relevance_score=0.7,
                        source="annotations"
                    ))
                
                return results
                
        except Exception as e:
            print(f"Error searching annotations: {e}")
            return []
    
    async def _search_highlights(self, query: str, user: UserContext, limit: int) -> List[SearchResult]:
        """Search highlights"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.supabase_url}/rest/v1/highlights",
                    headers=self._get_headers(),
                    params={
                        "user_id": f"eq.{user.user_id}",
                        "highlight_text.ilike": f"%{query}%",
                        "limit": str(limit),
                        "order": "created_at.desc"
                    }
                )
                response.raise_for_status()
                highlights = response.json()
                
                results = []
                for highlight in highlights:
                    results.append(SearchResult(
                        type="highlight",
                        id=highlight["id"],
                        title=f"Highlight: {highlight.get('highlight_text', '')[:50]}...",
                        content=highlight.get('highlight_text', ''),
                        relevance_score=0.6,
                        source="highlights"
                    ))
                
                return results
                
        except Exception as e:
            print(f"Error searching highlights: {e}")
            return [] 