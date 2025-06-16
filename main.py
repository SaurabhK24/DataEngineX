from dotenv import load_dotenv
load_dotenv('.env')  # Load environment variables FIRST

from fastapi import FastAPI, Query, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import os
from supabase import create_client, Client
from uuid import UUID
import httpx
from fastapi.responses import StreamingResponse
import io
from datetime import datetime

from app.models.paper import PaperResponse
from app.models.research_models import *
from app.controllers.paper_controller import PaperController
from app.controllers.research_controller import ResearchController
from app.controllers.knowledgebase_controller import router as knowledgebase_router, get_user_knowledgebases
from app.controllers.document_controller import router as document_router
from app.controllers.knowledge_canvas_controller import router as knowledge_canvas_router
from app.controllers.intelligent_search_controller import router as intelligent_search_router

app = FastAPI(
    title="DataEngineX",
    description="🧠 AI-Powered Research Platform - NotebookLM Competitor",
    version="3.0.0"
)

# Include routers for new features
app.include_router(knowledgebase_router)
app.include_router(document_router)
app.include_router(knowledge_canvas_router)
app.include_router(intelligent_search_router)

# Expose local PDF uploads
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Initialize controllers
paper_controller = PaperController()
research_controller = ResearchController()

# Initialize Supabase client for authentication
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service role key for backend operations
)

# Authentication dependency
async def get_current_user(authorization: Optional[str] = Header(None)) -> UserContext:
    """Extract user context from Supabase authorization header"""
    if not authorization:
        # Demo mode - use demo user
        return UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            email="demo@dataenginex.com",
            full_name="Demo User"
        )
    
    try:
        # Extract token from "Bearer <token>"
        token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
        
        # Validate token with Supabase
        user_response = supabase.auth.get_user(token)
        
        if user_response.user is None:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        
        user = user_response.user
        
        return UserContext(
            user_id=UUID(user.id),
            email=user.email or "",
            full_name=user.user_metadata.get("full_name") if user.user_metadata else None
        )
    except Exception as e:
        # For development/demo purposes, fallback to demo mode
        # In production, you might want to raise HTTPException(401, "Authentication required")
        return UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            email="demo@dataenginex.com", 
            full_name="Demo User"
        )

@app.get("/")
async def root():
    return {
        "message": "🧠 DataEngineX - AI Research Platform",
        "description": "NotebookLM competitor with AI-powered research capabilities",
        "features": [
            "📚 Research Library Management",
            "📄 PDF Upload & Processing", 
            "🔍 ArXiv Paper Discovery",
            "✏️ Annotations & Highlights",
            "💬 Chat with Papers (Llama 4)",
            "🔬 AI-Powered Analysis",
            "🔗 Knowledge Graphs",
            "🔎 Intelligent Search"
        ],
        "version": "3.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "DataEngineX Research Platform"}

# ============================================================================
# PAPER DISCOVERY (ArXiv Integration)
# ============================================================================

@app.get("/api/discover", response_model=List[PaperResponse])
async def discover_papers(
    q: str = Query(..., description="Search query for papers"),
    start: int = Query(0, ge=0, description="Starting index"),
    limit: int = Query(10, ge=1, le=50, description="Number of results"),
    sort: str = Query("relevance", description="Sort by: relevance, date, submitted"),
    order: str = Query("desc", description="Order: desc, asc")
):
    """
    🔍 Discover papers from ArXiv
    
    **Examples:**
    - `/api/discover?q=transformers&limit=5`
    - `/api/discover?q=machine learning&sort=date`
    """
    sort_mapping = {
        "relevance": "relevance",
        "date": "lastUpdatedDate", 
        "submitted": "submittedDate"
    }
    
    order_mapping = {
        "desc": "descending",
        "asc": "ascending"
    }
    
    return await paper_controller.search_arxiv(
        query=q,
        start=start,
        max_results=limit,
        sort_by=sort_mapping.get(sort, "relevance"),
        sort_order=order_mapping.get(order, "descending")
    )

@app.get("/api/discover/trending", response_model=List[PaperResponse])
async def discover_trending(
    limit: int = Query(20, ge=1, le=50, description="Number of trending papers")
):
    """📈 Discover trending papers from last 30 days"""
    return await paper_controller.get_trending_papers(limit)

@app.get("/api/discover/recommended", response_model=List[PaperResponse])
async def discover_recommended(
    limit: int = Query(15, ge=1, le=50, description="Number of recommended papers")
):
    """⭐ Get foundational papers in CS/ML"""
    return await paper_controller.get_recommended_papers(limit)

@app.get("/api/discover/category/{category}", response_model=List[PaperResponse])
async def discover_by_category(
    category: str,
    limit: int = Query(20, ge=1, le=50, description="Number of results")
):
    """🏷️ Discover papers by ArXiv category (cs.AI, cs.LG, cs.CV, etc.)"""
    return await paper_controller.search_arxiv(
        query=f"cat:{category}",
        max_results=limit,
        sort_by="submittedDate",
        sort_order="descending"
    )

@app.post("/api/discover/save/{paper_id}", response_model=PaperProcessResponse)
async def save_discovered_paper(
    paper_id: str,
    user: UserContext = Depends(get_current_user)
):
    """💾 Save a discovered ArXiv paper to your research library"""
    try:
        # First get the paper details
        papers = await paper_controller.search_arxiv(query=f"id:{paper_id}", max_results=1)
        if not papers:
            raise HTTPException(status_code=404, detail="Paper not found")
        
        paper = papers[0]
        return await research_controller.save_arxiv_paper(paper, user)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save paper: {str(e)}")

# ============================================================================
# RESEARCH LIBRARY MANAGEMENT
# ============================================================================

@app.post("/api/library/upload", response_model=PaperProcessResponse)
async def upload_paper(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    authors: Optional[str] = Form(None),  # Comma-separated
    abstract: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    topics: Optional[str] = Form(None),  # Comma-separated
    source: str = Form("upload")  # Add source parameter with default value
) -> PaperProcessResponse:
    
    #print("We have started the upload request brodie! At the start of the function")
    """
    📄 Upload a PDF paper to your research library
    
    Automatically extracts text and metadata using Llama 4
    """
    try:
        #print("started try block!")
        # Read file content
        file_content = await file.read()
        
        # Parse form data
        authors_list = authors.split(",") if authors else None
        topics_list = topics.split(",") if topics else None
        
        upload_request = PaperUploadRequest(
            file_name=file.filename,
            file_content=file_content,
            title=title,
            authors=authors_list,
            abstract=abstract,
            year=year,
            topics=topics_list
        )

        #print("We have created the upload request body. CALLING UPLOAD PAPER CONTROLLER FROM MAIN.PY")
        
        # Use a demo user context (no auth header required)
        user = UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            email="demo@dataenginex.com",
            full_name="Demo User"
        )
        
        return await research_controller.upload_paper(upload_request, user)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/api/download-pdf")
async def download_pdf_proxy(url: str):
    """
    📥 Download PDF from external URL (bypasses CORS)
    
    This endpoint acts as a proxy to download PDFs from external sources
    like ArXiv, avoiding CORS issues in the frontend.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            # Check if it's actually a PDF
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower():
                raise HTTPException(status_code=400, detail="URL does not return a PDF")
            
            # Return the PDF as a streaming response
            return StreamingResponse(
                io.BytesIO(response.content),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=paper.pdf"}
            )
            
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download PDF: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@app.get("/api/library", response_model=List[SavedPaper])
async def get_research_library(user: UserContext = Depends(get_current_user)):
    """📚 Get your complete research library"""
    return await research_controller.get_library(user)

@app.delete("/api/library/{paper_id}")
async def delete_paper(
    paper_id: UUID,
    user: UserContext = Depends(get_current_user)
):
    """🗑️ Remove a paper from your library"""
    # Implementation would delete from database
    return {"success": True, "message": f"Paper {paper_id} removed from library"}

# ============================================================================
# ANNOTATIONS & HIGHLIGHTS
# ============================================================================

@app.post("/api/papers/{paper_id}/highlights", response_model=HighlightResponse)
async def create_highlight(
    paper_id: UUID,
    request: CreateHighlightRequest,
    user: UserContext = Depends(get_current_user)
):
    """✏️ Create a highlight in a paper"""
    request.paper_id = paper_id
    return await research_controller.create_highlight(request, user)

@app.post("/api/papers/{paper_id}/annotations", response_model=AnnotationResponse)
async def create_annotation(
    paper_id: UUID,
    request: CreateAnnotationRequest,
    user: UserContext = Depends(get_current_user)
):
    """📝 Create an annotation (note, question, insight, critique)"""
    request.paper_id = paper_id
    return await research_controller.create_annotation(request, user)

@app.get("/api/papers/{paper_id}/highlights")
async def get_highlights(
    paper_id: UUID,
    user: UserContext = Depends(get_current_user)
):
    """Get all highlights for a paper"""
    # Implementation would fetch highlights from database
    return {"paper_id": paper_id, "highlights": []}

@app.get("/api/papers/{paper_id}/annotations")
async def get_annotations(
    paper_id: UUID,
    user: UserContext = Depends(get_current_user)
):
    """Get all annotations for a paper"""
    # Implementation would fetch annotations from database
    return {"paper_id": paper_id, "annotations": []}

# ============================================================================
# CHAT WITH PAPERS (Llama 4 Integration)
# ============================================================================

@app.post("/api/chat/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    request: ChatSessionRequest,
    user: UserContext = Depends(get_current_user)
):
    """💬 Create a chat session with a paper or your entire library"""
    return await research_controller.create_chat_session(request, user)

@app.post("/api/chat/message", response_model=ChatMessageResponse)
async def send_chat_message(
    request: ChatMessageRequest,
    user: UserContext = Depends(get_current_user)
):
    """
    🤖 Chat with your papers using Llama 4
    
    Ask questions, get insights, request summaries, etc.
    """
    return await research_controller.send_chat_message(request, user)

@app.get("/api/chat/sessions")
async def get_chat_sessions(user: UserContext = Depends(get_current_user)):
    """Get all your chat sessions"""
    # Implementation would fetch chat sessions from database
    return {"sessions": []}

@app.get("/api/chat/sessions/{session_id}/messages")
async def get_chat_messages(
    session_id: UUID,
    user: UserContext = Depends(get_current_user)
):
    """Get all messages in a chat session"""
    # Implementation would fetch messages from database
    return {"session_id": session_id, "messages": []}

# ============================================================================
# AI-POWERED ANALYSIS
# ============================================================================

@app.post("/api/papers/{paper_id}/analyze", response_model=AnalysisResponse)
async def analyze_paper(
    paper_id: UUID,
    request: AnalysisRequest,
    user: UserContext = Depends(get_current_user)
):
    """
    🔬 Analyze a paper using Llama 4
    
    **Analysis types:**
    - `summary` - Key findings and contributions
    - `methodology` - Research methods analysis  
    - `critique` - Critical evaluation
    - `key_points` - Extract main points
    """
    request.paper_id = paper_id
    return await research_controller.analyze_paper(request, user)

@app.post("/api/compare", response_model=ComparisonResponse)
async def compare_papers(
    request: CompareRequest,
    user: UserContext = Depends(get_current_user)
):
    """🔍 Compare multiple papers using Llama 4"""
    # Implementation would use Llama to compare papers
    return ComparisonResponse(
        papers=[],
        similarities=[],
        differences=[],
        synthesis="Comparison analysis would be generated here",
        recommendations=[]
    )

@app.get("/api/papers/{paper_id}/insights")
async def get_paper_insights(
    paper_id: UUID,
    user: UserContext = Depends(get_current_user)
):
    """💡 Get AI-generated insights for a paper"""
    # Implementation would fetch stored analyses and insights
    return {"paper_id": paper_id, "insights": []}

# ============================================================================
# SEARCH & DISCOVERY
# ============================================================================

@app.post("/api/search", response_model=SearchResponse)
async def search_library(
    request: SearchRequest,
    user: UserContext = Depends(get_current_user)
):
    """
    🔎 Search across your entire research library
    
    Search papers, annotations, highlights, and notes
    """
    return await research_controller.search_library(request, user)

@app.get("/api/search/quick")
async def quick_search(
    q: str = Query(..., description="Quick search query"),
    user: UserContext = Depends(get_current_user)
):
    """⚡ Quick search across all content"""
    request = SearchRequest(query=q, limit=10)
    return await research_controller.search_library(request, user)

# ============================================================================
# CONCEPTS & KNOWLEDGE GRAPH
# ============================================================================

@app.post("/api/concepts", response_model=ConceptResponse)
async def create_concept(
    request: CreateConceptRequest,
    user: UserContext = Depends(get_current_user)
):
    """🧠 Create a research concept for knowledge mapping"""
    # Implementation would create concept in database
    return ConceptResponse(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        name=request.name,
        description=request.description,
        concept_type=request.concept_type,
        color=request.color,
        linked_papers=0,
        linked_annotations=0,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z"
    )

@app.get("/api/concepts")
async def get_concepts(user: UserContext = Depends(get_current_user)):
    """Get all your research concepts"""
    return {"concepts": []}

@app.post("/api/concepts/link")
async def link_concept(
    request: LinkConceptRequest,
    user: UserContext = Depends(get_current_user)
):
    """🔗 Link a concept to papers, annotations, or highlights"""
    return {"success": True, "message": "Concept linked successfully"}

# ============================================================================
# COLLECTIONS & WORKFLOWS
# ============================================================================

@app.post("/api/collections", response_model=CollectionResponse)
async def create_collection(
    request: CreateCollectionRequest,
    user: UserContext = Depends(get_current_user)
):
    """📂 Create a research collection (group of related papers)"""
    collection_id = UUID("00000000-0000-0000-0000-000000000000")
    return CollectionResponse(
        id=collection_id,
        name=request.name,
        description=request.description,
        papers_count=len(request.paper_ids),
        is_public=request.is_public,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z"
    )

@app.get("/api/collections")
async def get_collections(user: UserContext = Depends(get_current_user)):
    """Get all your research collections"""
    return {"collections": []}

# ============================================================================
# STATISTICS & DASHBOARD
# ============================================================================

@app.get("/api/stats", response_model=LibraryStatsResponse)
async def get_library_stats(user: UserContext = Depends(get_current_user)):
    """📊 Get your research library statistics"""
    return LibraryStatsResponse(
        total_papers=0,
        total_annotations=0,
        total_highlights=0,
        total_concepts=0,
        total_collections=0,
        recent_activity=[],
        storage_used_mb=0.0,
        last_updated="2024-01-01T00:00:00Z"
    )

@app.get("/api/dashboard")
async def get_dashboard(user: UserContext = Depends(get_current_user)):
    """🎛️ Get dashboard data with quick stats and AI insights"""
    # Fetch real stats from DB
    # Papers
    papers = await research_controller.get_library(user)
    total_papers = len(papers)
    # Annotations
    async with httpx.AsyncClient() as client:
        annotations_resp = await client.get(
            f"{research_controller.supabase_url}/rest/v1/annotations",
            headers=research_controller._get_headers(),
            params={"user_id": f"eq.{str(user.user_id)}"}
        )
        total_annotations = len(annotations_resp.json())
        highlights_resp = await client.get(
            f"{research_controller.supabase_url}/rest/v1/highlights",
            headers=research_controller._get_headers(),
            params={"user_id": f"eq.{str(user.user_id)}"}
        )
        total_highlights = len(highlights_resp.json())
        chat_sessions_resp = await client.get(
            f"{research_controller.supabase_url}/rest/v1/chat_sessions",
            headers=research_controller._get_headers(),
            params={"user_id": f"eq.{str(user.user_id)}"}
        )
        total_chat_sessions = len(chat_sessions_resp.json())
    # Knowledge Bases
    try:
        knowledge_bases = await get_user_knowledgebases(user.user_id)
        total_knowledgebases = len(knowledge_bases)
    except Exception:
        total_knowledgebases = 0
    quick_stats = {
        "total_papers": total_papers,
        "total_annotations": total_annotations,
        "total_highlights": total_highlights,
        "total_concepts": 0,  # Not implemented
        "total_collections": 0,  # Not implemented
        "total_knowledgebases": total_knowledgebases,
        "total_chat_sessions": total_chat_sessions,
        "recent_activity": [],
        "storage_used_mb": 0.0,
        "research_metrics": {},
        "last_updated": datetime.now().isoformat()
    }
    # Only run AI insights on the last two most recent papers
    ai_insights = []
    if papers:
        # Sort papers by created_at or fallback to id (if no created_at)
        sorted_papers = sorted(
            papers,
            key=lambda p: getattr(p, 'created_at', None) or getattr(p, 'id', None),
            reverse=True
        )
        for paper in sorted_papers[:2]:
            try:
                analysis = await research_controller.analyze_paper(
                    AnalysisRequest(paper_id=paper.id, analysis_type="summary"), user
                )
                ai_insights.append({
                    "paper_id": str(paper.id),
                    "title": paper.title,
                    "insights": analysis.insights
                })
            except Exception:
                ai_insights.append({
                    "paper_id": str(paper.id),
                    "title": paper.title,
                    "insights": []
                })
    return {
        "quick_stats": quick_stats,
        "ai_insights": ai_insights
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
