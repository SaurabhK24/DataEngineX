"""
Document Controller
Handles document viewing, annotations, highlights, and document-specific chat for DelphiX frontend
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional, Dict, Any
from uuid import UUID
import json
from datetime import datetime

from ..models.research_models import (
    DocumentResponse,
    HighlightRequest,
    HighlightUpdateRequest,
    DocumentAnnotationRequest,
    DocumentChatRequest,
    DocumentChatResponse
)
from ..utils.supabase_client import get_supabase
from ..utils.auth import get_current_user_id
from ..services.llama_client import LlamaClient

router = APIRouter(prefix="/api/documents", tags=["Documents"])

# ============================================================================
# DOCUMENT METADATA AND ACCESS
# ============================================================================

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get document metadata for the PDF viewer"""
    try:
        supabase = get_supabase()
        
        # Get paper information (documents are papers in our system)
        paper_result = supabase.table('papers').select('*').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        paper = paper_result.data[0]
        
        # Count pages if available (this would require PDF processing)
        # For now, we'll set a default or derive from processing metadata
        page_count = paper.get('metadata', {}).get('page_count') if paper.get('metadata') else None
        
        return DocumentResponse(
            id=document_id,
            title=paper['title'],
            authors=paper.get('authors', []),
            pdfUrl=paper['pdf_url'],
            abstract=paper.get('abstract'),
            year=paper.get('year'),
            topics=paper.get('topics', []),
            page_count=page_count,
            processing_status=paper.get('processing_status', 'completed')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching document: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch document")

# ============================================================================
# HIGHLIGHTS MANAGEMENT
# ============================================================================

@router.get("/{document_id}/annotations")
async def get_document_annotations(
    document_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get all highlights and annotations for a document"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('id').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        # Get highlights
        highlights_result = supabase.table('highlights').select('*').eq('paper_id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        # Get annotations
        annotations_result = supabase.table('annotations').select('*').eq('paper_id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        # Transform highlights to match frontend format
        highlights = []
        for h in highlights_result.data or []:
            highlight = {
                'id': h['id'],
                'position': h['position'],
                'content': {'text': h.get('highlight_text', '')},
                'type': h.get('highlight_type', 'text'),
                'color': h.get('color', '#FFFF00'),
                'comment': h.get('comment'),
                'timestamp': h['created_at']
            }
            highlights.append(highlight)
        
        # Transform annotations
        annotations = []
        for a in annotations_result.data or []:
            annotation = {
                'id': a['id'],
                'type': a.get('annotation_type', 'note'),
                'content': a['content'],
                'page': a.get('page_number'),
                'position': a.get('position'),
                'timestamp': a['created_at'],
                'highlight_id': a.get('highlight_id')
            }
            annotations.append(annotation)
        
        return {
            'highlights': highlights,
            'annotations': annotations
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching annotations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch annotations")

@router.post("/{document_id}/highlights")
async def save_highlight(
    document_id: UUID,
    request: HighlightRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Save a new highlight"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('id').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        # Extract text content for storage
        highlight_text = request.content.get('text', '') if request.content else ''
        page_number = request.position.get('pageNumber', 1) if request.position else 1
        
        # Save highlight
        highlight_result = supabase.table('highlights').insert({
            'user_id': str(user_id),
            'paper_id': str(document_id),
            'highlight_text': highlight_text,
            'page_number': page_number,
            'position': request.position,
            'color': request.color,
            'highlight_type': request.type,
            'comment': request.comment,
            'metadata': {
                'content': request.content,
                'created_via': 'pdf_viewer'
            }
        }).execute()
        
        if not highlight_result.data:
            raise HTTPException(status_code=400, detail="Failed to save highlight")
        
        # Log activity
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'highlight_create',
            document_id,
            {'page': page_number, 'text_length': len(highlight_text)}
        )
        
        # Return the created highlight in frontend format
        highlight = highlight_result.data[0]
        return {
            'id': highlight['id'],
            'position': highlight['position'],
            'content': request.content,
            'type': request.type,
            'color': request.color,
            'comment': request.comment,
            'timestamp': highlight['created_at']
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error saving highlight: {e}")
        raise HTTPException(status_code=500, detail="Failed to save highlight")

@router.put("/{document_id}/highlights/{highlight_id}")
async def update_highlight(
    document_id: UUID,
    highlight_id: UUID,
    request: HighlightUpdateRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Update an existing highlight"""
    try:
        supabase = get_supabase()
        
        # Verify highlight ownership
        highlight_result = supabase.table('highlights').select('*').eq('id', str(highlight_id)).eq('user_id', str(user_id)).eq('paper_id', str(document_id)).execute()
        
        if not highlight_result.data:
            raise HTTPException(status_code=404, detail="Highlight not found or access denied")
        
        # Prepare update data
        update_data = {}
        if request.comment is not None:
            update_data['comment'] = request.comment
        if request.color is not None:
            update_data['color'] = request.color
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Update highlight
        result = supabase.table('highlights').update(update_data).eq('id', str(highlight_id)).execute()
        
        if not result.data:
            raise HTTPException(status_code=400, detail="Failed to update highlight")
        
        # Log activity
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'highlight_update',
            document_id,
            {'highlight_id': str(highlight_id)}
        )
        
        return {"message": "Highlight updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating highlight: {e}")
        raise HTTPException(status_code=500, detail="Failed to update highlight")

@router.delete("/{document_id}/highlights/{highlight_id}")
async def delete_highlight(
    document_id: UUID,
    highlight_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Delete a highlight"""
    try:
        supabase = get_supabase()
        
        # Verify highlight ownership
        highlight_result = supabase.table('highlights').select('id').eq('id', str(highlight_id)).eq('user_id', str(user_id)).eq('paper_id', str(document_id)).execute()
        
        if not highlight_result.data:
            raise HTTPException(status_code=404, detail="Highlight not found or access denied")
        
        # Delete highlight
        result = supabase.table('highlights').delete().eq('id', str(highlight_id)).execute()
        
        if not result.data:
            raise HTTPException(status_code=400, detail="Failed to delete highlight")
        
        # Log activity
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'highlight_delete',
            document_id,
            {'highlight_id': str(highlight_id)}
        )
        
        return {"message": "Highlight deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting highlight: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete highlight")

# ============================================================================
# ANNOTATIONS MANAGEMENT
# ============================================================================

@router.post("/{document_id}/annotations")
async def save_annotation(
    document_id: UUID,
    request: DocumentAnnotationRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Save a new annotation"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('id').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        # Save annotation
        annotation_result = supabase.table('annotations').insert({
            'user_id': str(user_id),
            'paper_id': str(document_id),
            'content': request.content,
            'annotation_type': request.type,
            'page_number': request.page,
            'position': request.position,
            'tags': []  # Can be extended later
        }).execute()
        
        if not annotation_result.data:
            raise HTTPException(status_code=400, detail="Failed to save annotation")
        
        # Log activity
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'annotation_create',
            document_id,
            {'type': request.type, 'page': request.page}
        )
        
        return {
            'id': annotation_result.data[0]['id'],
            'message': 'Annotation saved successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error saving annotation: {e}")
        raise HTTPException(status_code=500, detail="Failed to save annotation")

# ============================================================================
# DOCUMENT CHAT
# ============================================================================

@router.post("/{document_id}/chat", response_model=DocumentChatResponse)
async def send_document_chat_message(
    document_id: UUID,
    request: DocumentChatRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Send a chat message about the document"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('*').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        paper = paper_result.data[0]
        
        # Save user message
        user_message_result = supabase.table('document_chat_messages').insert({
            'user_id': str(user_id),
            'paper_id': str(document_id),
            'role': 'user',
            'content': request.message,
            'context': request.context or {},
            'sources': []
        }).execute()
        
        # Generate AI response
        llama_client = LlamaClient()
        
        # Build context for AI
        context_info = ""
        if request.context:
            if request.context.get('highlights'):
                # Validate and filter highlight IDs to ensure they are proper UUID strings
                valid_highlight_ids = []
                for hid in request.context.get('highlights', []):
                    try:
                        # Attempt to cast to UUID to validate; store as str for Supabase query
                        valid_highlight_ids.append(str(UUID(str(hid))))
                    except (ValueError, TypeError):
                        # Ignore invalid UUIDs
                        continue

                if valid_highlight_ids:
                    # Get highlighted text only for valid IDs
                    highlights_result = supabase.table('highlights').select('highlight_text').in_('id', valid_highlight_ids).execute()
                    if highlights_result.data:
                        highlighted_texts = [h['highlight_text'] for h in highlights_result.data]
                        context_info += f"\n\nHighlighted text:\n" + "\n".join(highlighted_texts)
                else:
                    # No valid highlight IDs provided; warn but continue gracefully
                    print("Warning: No valid highlight UUIDs provided in chat context")
            
            if request.context.get('page'):
                context_info += f"\n\nPage reference: {request.context['page']}"
        
        # Prepare AI prompt
        prompt = f"""
        You are an AI research assistant helping a user understand a research paper.
        
        Paper: "{paper['title']}"
        Abstract: {paper.get('abstract', 'No abstract available')}
        
        User's question: {request.message}
        {context_info}
        
        Provide a helpful, accurate response based on the paper content and context provided.
        If you reference specific content, be clear about what you're citing.
        """
        
        ai_response = await llama_client.generate_response(prompt)
        
        # Save AI response
        ai_message_result = supabase.table('document_chat_messages').insert({
            'user_id': str(user_id),
            'paper_id': str(document_id),
            'role': 'assistant',
            'content': ai_response,
            'context': request.context or {},
            'sources': valid_highlight_ids if request.context else []
        }).execute()
        
        # Log activity
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'document_chat',
            document_id,
            {'message_length': len(request.message)}
        )
        
        return DocumentChatResponse(
            id=ai_message_result.data[0]['id'],
            message=ai_response,
            sources=valid_highlight_ids if request.context else [],
            timestamp=ai_message_result.data[0]['created_at']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in document chat: {e}")
        raise HTTPException(status_code=500, detail="Failed to process chat message")

@router.get("/{document_id}/chat")
async def get_document_chat_history(
    document_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get chat history for a document"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('id').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        # Get chat messages
        messages_result = supabase.table('document_chat_messages').select('*').eq('paper_id', str(document_id)).eq('user_id', str(user_id)).order('created_at').execute()
        
        # Transform messages for frontend
        messages = []
        for msg in messages_result.data or []:
            message = {
                'id': msg['id'],
                'type': msg['role'],
                'content': msg['content'],
                'timestamp': msg['created_at'],
                'context': msg.get('context'),
                'highlights': msg.get('sources', [])
            }
            messages.append(message)
        
        return messages
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching chat history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")

# ============================================================================
# DOCUMENT ANALYTICS
# ============================================================================

@router.post("/{document_id}/view")
async def track_document_view(
    document_id: UUID,
    view_data: Dict[str, Any],
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Track document viewing session"""
    try:
        supabase = get_supabase()
        
        # Verify document access
        paper_result = supabase.table('papers').select('id').eq('id', str(document_id)).eq('user_id', str(user_id)).execute()
        
        if not paper_result.data:
            raise HTTPException(status_code=404, detail="Document not found or access denied")
        
        # Update or create view record
        session_id = view_data.get('session_id', 'default')
        
        # Try to get existing view session
        view_result = supabase.table('document_views').select('*').eq('paper_id', str(document_id)).eq('user_id', str(user_id)).eq('session_id', session_id).execute()
        
        if view_result.data:
            # Update existing session
            update_data = {
                'last_page': view_data.get('current_page', 1),
                'time_spent': view_data.get('time_spent', 0),
                'zoom_level': view_data.get('zoom_level', 1.0),
                'updated_at': datetime.now().isoformat()
            }
            
            if 'pages_viewed' in view_data:
                # Merge with existing pages
                existing_pages = view_result.data[0].get('pages_viewed', [])
                new_pages = view_data['pages_viewed']
                merged_pages = list(set(existing_pages + new_pages))
                update_data['pages_viewed'] = merged_pages
            
            supabase.table('document_views').update(update_data).eq('id', view_result.data[0]['id']).execute()
        else:
            # Create new view session
            supabase.table('document_views').insert({
                'user_id': str(user_id),
                'paper_id': str(document_id),
                'session_id': session_id,
                'pages_viewed': view_data.get('pages_viewed', []),
                'time_spent': view_data.get('time_spent', 0),
                'last_page': view_data.get('current_page', 1),
                'zoom_level': view_data.get('zoom_level', 1.0)
            }).execute()
        
        # Log activity in background
        background_tasks.add_task(
            log_document_activity,
            user_id,
            'document_view',
            document_id,
            view_data
        )
        
        return {"message": "View tracked successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error tracking document view: {e}")
        raise HTTPException(status_code=500, detail="Failed to track view")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def log_document_activity(user_id: UUID, activity_type: str, document_id: UUID, metadata: dict = None):
    """Log document-related activity"""
    try:
        supabase = get_supabase()
        supabase.rpc('log_user_activity', {
            'p_user_id': str(user_id),
            'p_activity_type': activity_type,
            'p_entity_type': 'document',
            'p_entity_id': str(document_id),
            'p_metadata': json.dumps(metadata or {})
        }).execute()
    except Exception as e:
        print(f"Error logging document activity: {e}") 