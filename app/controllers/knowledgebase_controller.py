"""
Knowledge Base Controller
Handles knowledge base creation, management, and operations for the DelphiX frontend
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
from uuid import UUID
import json
from datetime import datetime

from ..models.research_models import (
    CreateKnowledgebaseRequest,
    KnowledgebaseResponse, 
    UpdateKnowledgebaseRequest,
    AddPapersToKnowledgebaseRequest,
    RemovePapersFromKnowledgebaseRequest,
    ShareKnowledgebaseRequest,
    KnowledgebaseInsightsResponse,
    ExportRequest,
    ExportResponse
)
from ..utils.supabase_client import get_supabase
from ..utils.auth import get_current_user_id
from ..services.llama_client import LlamaClient

router = APIRouter(prefix="/api/knowledgebases", tags=["Knowledge Bases"])

# ============================================================================
# KNOWLEDGE BASE CRUD OPERATIONS
# ============================================================================

@router.get("/", response_model=List[KnowledgebaseResponse])
async def get_user_knowledgebases(
    user_id: UUID = Depends(get_current_user_id)
):
    """Get all knowledge bases for the current user"""
    try:
        print(f"DEBUG: get_user_knowledgebases called with user_id: {user_id}")
        supabase = get_supabase()
        
        # Direct query instead of database function
        result = supabase.table('knowledge_bases').select('*').eq('user_id', str(user_id)).order('updated_at', desc=True).execute()
        
        print(f"DEBUG: Database query result: {result}")
        print(f"DEBUG: Number of knowledge bases found: {len(result.data) if result.data else 0}")
        
        if result.data:
            print(f"DEBUG: Found {len(result.data)} knowledge bases for user {user_id}")
            knowledge_bases = []
            for kb_data in result.data:
                print(f"DEBUG: Processing KB: {kb_data['name']} (id: {kb_data['id']})")
                # Get paper count separately
                paper_count_result = supabase.table('knowledge_base_papers').select('id', count='exact').eq('knowledge_base_id', kb_data['id']).execute()
                paper_count = paper_count_result.count or 0
                
                kb = KnowledgebaseResponse(
                    id=kb_data['id'],
                    name=kb_data['name'],
                    description=kb_data.get('description'),
                    paper_count=paper_count,
                    created_at=kb_data['created_at'],
                    updated_at=kb_data['updated_at'],
                    tags=kb_data.get('tags', []),
                    status=kb_data.get('status', 'active'),
                    user_id=user_id,
                    is_public=kb_data.get('is_public', False)
                )
                knowledge_bases.append(kb)
            print(f"DEBUG: Returning {len(knowledge_bases)} knowledge bases")
            return knowledge_bases
        
        print(f"DEBUG: No knowledge bases found for user {user_id}, returning empty list")
        return []
        
    except Exception as e:
        print(f"Error fetching knowledge bases: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge bases")

@router.post("/", response_model=KnowledgebaseResponse)
async def create_knowledgebase(
    request: CreateKnowledgebaseRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Create a new knowledge base"""
    try:
        supabase = get_supabase()
        
        # Create the knowledge base
        kb_result = supabase.table('knowledge_bases').insert({
            'user_id': str(user_id),
            'name': request.name,
            'description': request.description,
            'tags': request.tags,
            'is_public': request.is_public,
            'status': 'active'
        }).execute()
        
        if not kb_result.data:
            raise HTTPException(status_code=400, detail="Failed to create knowledge base")
        
        kb_id = kb_result.data[0]['id']
        
        # Add papers if provided
        if request.papers:
            paper_entries = []
            for paper_id in request.papers:
                paper_entries.append({
                    'knowledge_base_id': kb_id,
                    'paper_id': paper_id,
                    'added_by': str(user_id)
                })
            
            supabase.table('knowledge_base_papers').insert(paper_entries).execute()
        
        # Log activity
        background_tasks.add_task(
            log_activity, 
            user_id, 
            'knowledge_base_create', 
            'knowledge_base', 
            kb_id
        )
        
        # Generate analysis immediately for new knowledge base
        if request.papers:
            # Get full paper data
            papers = []
            for paper_id in request.papers:
                paper_result = supabase.table('papers').select('*').eq('id', paper_id).execute()
                if paper_result.data:
                    papers.append(paper_result.data[0])
            
            if papers:
                # Generate all analyses before returning
                await generate_kb_analysis(UUID(kb_id), papers, request.name)
        
        # Return the created knowledge base
        return KnowledgebaseResponse(
            id=kb_id,
            name=request.name,
            description=request.description,
            paper_count=len(request.papers),
            created_at=kb_result.data[0]['created_at'],
            updated_at=kb_result.data[0]['updated_at'],
            tags=request.tags,
            status='active',
            user_id=user_id,
            is_public=request.is_public
        )
        
    except Exception as e:
        print(f"Error creating knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to create knowledge base")

@router.get("/{kb_id}", response_model=KnowledgebaseResponse)
async def get_knowledgebase(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get a specific knowledge base by ID"""
    try:
        supabase = get_supabase()
        
        # Use the database function
        result = supabase.rpc('get_knowledge_base_stats', {'p_kb_id': str(kb_id)}).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        kb_data = result.data
        
        # Check if user has access (owner or shared)
        access_result = supabase.table('knowledge_bases').select('user_id, is_public').eq('id', str(kb_id)).execute()
        
        if not access_result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        kb_info = access_result.data[0]
        
        # Check access permissions
        if (kb_info['user_id'] != str(user_id) and 
            not kb_info['is_public']):
            
            # Check if shared with user
            share_result = supabase.table('knowledge_base_shares').select('id').eq('knowledge_base_id', str(kb_id)).eq('shared_with_user_id', str(user_id)).execute()
            
            if not share_result.data:
                raise HTTPException(status_code=403, detail="Access denied to knowledge base")
        
        return KnowledgebaseResponse(
            id=kb_data['id'],
            name=kb_data['name'],
            description=kb_data.get('description'),
            paper_count=kb_data['paper_count'],
            created_at=kb_data['created_at'],
            updated_at=kb_data['updated_at'],
            tags=kb_data.get('tags', []),
            status=kb_data.get('status', 'active'),
            user_id=UUID(kb_info['user_id']),
            is_public=kb_data.get('is_public', False)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge base")

@router.put("/{kb_id}", response_model=KnowledgebaseResponse)
async def update_knowledgebase(
    kb_id: UUID,
    request: UpdateKnowledgebaseRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Update a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check ownership
        kb_result = supabase.table('knowledge_bases').select('user_id').eq('id', str(kb_id)).execute()
        
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Prepare update data
        update_data = {'updated_at': datetime.now().isoformat()}
        
        if request.name is not None:
            update_data['name'] = request.name
        if request.description is not None:
            update_data['description'] = request.description
        if request.tags is not None:
            update_data['tags'] = request.tags
        if request.is_public is not None:
            update_data['is_public'] = request.is_public
        
        # Update knowledge base
        result = supabase.table('knowledge_bases').update(update_data).eq('id', str(kb_id)).execute()
        
        if not result.data:
            raise HTTPException(status_code=400, detail="Failed to update knowledge base")
        
        # Handle papers update if provided
        if request.papers is not None:
            # Remove existing papers
            supabase.table('knowledge_base_papers').delete().eq('knowledge_base_id', str(kb_id)).execute()
            
            # Add new papers
            if request.papers:
                paper_entries = []
                for paper_id in request.papers:
                    paper_entries.append({
                        'knowledge_base_id': str(kb_id),
                        'paper_id': paper_id,
                        'added_by': str(user_id)
                    })
                
                supabase.table('knowledge_base_papers').insert(paper_entries).execute()
        
        # Log activity
        background_tasks.add_task(
            log_activity, 
            user_id, 
            'knowledge_base_update', 
            'knowledge_base', 
            kb_id
        )
        
        # Get updated knowledge base
        updated_kb = supabase.rpc('get_knowledge_base_stats', {'p_kb_id': str(kb_id)}).execute()
        kb_data = updated_kb.data
        
        return KnowledgebaseResponse(
            id=kb_data['id'],
            name=kb_data['name'],
            description=kb_data.get('description'),
            paper_count=kb_data['paper_count'],
            created_at=kb_data['created_at'],
            updated_at=kb_data['updated_at'],
            tags=kb_data.get('tags', []),
            status=kb_data.get('status', 'active'),
            user_id=user_id,
            is_public=kb_data.get('is_public', False)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to update knowledge base")

@router.delete("/{kb_id}")
async def delete_knowledgebase(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Delete a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check ownership
        kb_result = supabase.table('knowledge_bases').select('user_id').eq('id', str(kb_id)).execute()
        
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Delete knowledge base (cascade will handle related records)
        result = supabase.table('knowledge_bases').delete().eq('id', str(kb_id)).execute()
        
        if not result.data:
            raise HTTPException(status_code=400, detail="Failed to delete knowledge base")
        
        # Log activity
        background_tasks.add_task(
            log_activity, 
            user_id, 
            'knowledge_base_delete', 
            'knowledge_base', 
            kb_id
        )
        
        return {"message": "Knowledge base deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete knowledge base")

# ============================================================================
# PAPER MANAGEMENT IN KNOWLEDGE BASES
# ============================================================================

@router.get("/{kb_id}/papers")
async def get_knowledgebase_papers(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get all papers in a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check access to knowledge base
        kb_result = supabase.table('knowledge_bases').select('user_id, is_public').eq('id', str(kb_id)).execute()
        
        if not kb_result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        kb_info = kb_result.data[0]
        
        # Check permissions
        if (kb_info['user_id'] != str(user_id) and not kb_info['is_public']):
            share_result = supabase.table('knowledge_base_shares').select('id').eq('knowledge_base_id', str(kb_id)).eq('shared_with_user_id', str(user_id)).execute()
            if not share_result.data:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Get papers using direct query instead of database function
        # This avoids the GROUP BY issue with kbp.added_at
        result = supabase.table('knowledge_base_papers').select(
            'paper_id, papers(id, title, abstract, authors, year, citations, pdf_url, topics)'
        ).eq('knowledge_base_id', str(kb_id)).execute()
        
        # Transform the result to extract paper data
        papers = []
        if result.data:
            for item in result.data:
                if item.get('papers'):
                    paper = item['papers']
                    # Add generated quality and relevance scores
                    # In a real implementation, you could use LLM to analyze the abstract
                    # For now, we'll use a simple heuristic based on citations
                    citations = paper.get('citations', 0)
                    
                    # Quality score based on citations (0-100 scale)
                    if citations > 10000:
                        quality_score = 95
                    elif citations > 5000:
                        quality_score = 90
                    elif citations > 1000:
                        quality_score = 85
                    elif citations > 500:
                        quality_score = 80
                    elif citations > 100:
                        quality_score = 75
                    else:
                        quality_score = 70
                    
                    # Add computed fields
                    paper['quality_score'] = quality_score
                    paper['relevance_score'] = 85  # Default relevance score
                    
                    papers.append(paper)
        
        return papers
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching knowledge base papers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch papers")

@router.post("/{kb_id}/papers")
async def add_papers_to_knowledgebase(
    kb_id: UUID,
    request: AddPapersToKnowledgebaseRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Add papers to a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check ownership or write permission
        kb_result = supabase.table('knowledge_bases').select('user_id').eq('id', str(kb_id)).execute()
        
        if not kb_result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        if kb_result.data[0]['user_id'] != str(user_id):
            # Check if user has write permission
            share_result = supabase.table('knowledge_base_shares').select('permissions').eq('knowledge_base_id', str(kb_id)).eq('shared_with_user_id', str(user_id)).execute()
            
            if not share_result.data or share_result.data[0]['permissions'] not in ['write', 'admin']:
                raise HTTPException(status_code=403, detail="Write access required")
        
        # Add papers
        paper_entries = []
        for paper_id in request.paper_ids:
            paper_entries.append({
                'knowledge_base_id': str(kb_id),
                'paper_id': paper_id,
                'added_by': str(user_id)
            })
        
        result = supabase.table('knowledge_base_papers').upsert(paper_entries, on_conflict='knowledge_base_id,paper_id').execute()
        
        # Update knowledge base timestamp
        supabase.table('knowledge_bases').update({
            'updated_at': datetime.now().isoformat()
        }).eq('id', str(kb_id)).execute()
        
        # Log activity
        background_tasks.add_task(
            log_activity, 
            user_id, 
            'papers_added_to_kb', 
            'knowledge_base', 
            kb_id,
            {'paper_count': len(request.paper_ids)}
        )
        
        return {"message": f"Added {len(request.paper_ids)} papers to knowledge base"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error adding papers to knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to add papers")

@router.delete("/{kb_id}/papers")
async def remove_papers_from_knowledgebase(
    kb_id: UUID,
    request: RemovePapersFromKnowledgebaseRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Remove papers from a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check ownership or write permission
        kb_result = supabase.table('knowledge_bases').select('user_id').eq('id', str(kb_id)).execute()
        
        if not kb_result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        if kb_result.data[0]['user_id'] != str(user_id):
            share_result = supabase.table('knowledge_base_shares').select('permissions').eq('knowledge_base_id', str(kb_id)).eq('shared_with_user_id', str(user_id)).execute()
            
            if not share_result.data or share_result.data[0]['permissions'] not in ['write', 'admin']:
                raise HTTPException(status_code=403, detail="Write access required")
        
        # Remove papers
        for paper_id in request.paper_ids:
            supabase.table('knowledge_base_papers').delete().eq('knowledge_base_id', str(kb_id)).eq('paper_id', paper_id).execute()
        
        # Update knowledge base timestamp
        supabase.table('knowledge_bases').update({
            'updated_at': datetime.now().isoformat()
        }).eq('id', str(kb_id)).execute()
        
        # Log activity
        background_tasks.add_task(
            log_activity, 
            user_id, 
            'papers_removed_from_kb', 
            'knowledge_base', 
            kb_id,
            {'paper_count': len(request.paper_ids)}
        )
        
        return {"message": f"Removed {len(request.paper_ids)} papers from knowledge base"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error removing papers from knowledge base: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove papers")

# ============================================================================
# AI INSIGHTS AND ANALYSIS
# ============================================================================

@router.post("/{kb_id}/generate-analysis")
async def generate_knowledgebase_analysis(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id)
):
    """Generate comprehensive analysis for all KB tabs"""
    try:
        supabase = get_supabase()
        
        # Check access
        kb_result = supabase.table('knowledge_bases').select('user_id, name').eq('id', str(kb_id)).execute()
        
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get papers in knowledge base with full content
        papers_result = supabase.table('knowledge_base_papers').select(
            'papers(id, title, abstract, authors, year, citations, pdf_url, topics, full_text)'
        ).eq('knowledge_base_id', str(kb_id)).execute()
        
        if not papers_result.data:
            raise HTTPException(status_code=400, detail="No papers in knowledge base to analyze")
        
        # Extract papers
        papers = []
        for item in papers_result.data:
            if item.get('papers'):
                papers.append(item['papers'])
        
        # Generate analysis for all tabs
        analysis = await generate_kb_analysis(kb_id, papers, kb_result.data[0]['name'])
        
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating analysis: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate analysis")

@router.post("/{kb_id}/generate-connections")
async def generate_knowledgebase_connections(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Generate only connections analysis for a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check access and get papers
        kb_result = supabase.table('knowledge_bases').select('user_id, name').eq('id', str(kb_id)).execute()
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Fetch full_text for each paper
        papers_result = supabase.table('knowledge_base_papers').select(
            'papers(id, title, abstract, authors, year, citations, topics, full_text)'
        ).eq('knowledge_base_id', str(kb_id)).execute()
        
        papers = []
        for item in papers_result.data:
            if item.get('papers'):
                papers.append(item['papers'])
        
        if not papers:
            raise HTTPException(status_code=400, detail="No papers in knowledge base")
        
        # Generate connections only
        connections = await generate_connections_analysis(kb_id, papers, kb_result.data[0]['name'])
        
        # Update only connections in database
        analysis_result = supabase.table('knowledge_base_analysis').select('*').eq('knowledge_base_id', str(kb_id)).execute()
        
        if analysis_result.data:
            # Update existing record
            supabase.table('knowledge_base_analysis').update({
                'connections': connections,
                'updated_at': datetime.now().isoformat()
            }).eq('knowledge_base_id', str(kb_id)).execute()
        else:
            # Create new record with just connections
            supabase.table('knowledge_base_analysis').insert({
                'knowledge_base_id': str(kb_id),
                'connections': connections,
                'insights': {},
                'analytics': {},
                'generated_by': 'llama-4',
                'created_at': datetime.now().isoformat()
            }).execute()
        
        return connections
        
    except Exception as e:
        print(f"Error generating connections: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate connections")

@router.post("/{kb_id}/generate-insights")
async def generate_knowledgebase_insights_endpoint(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Generate only insights analysis for a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check access and get papers
        kb_result = supabase.table('knowledge_bases').select('user_id, name').eq('id', str(kb_id)).execute()
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        papers_result = supabase.table('knowledge_base_papers').select(
            'papers(id, title, abstract, authors, year, citations, topics)'
        ).eq('knowledge_base_id', str(kb_id)).execute()
        
        papers = []
        for item in papers_result.data:
            if item.get('papers'):
                papers.append(item['papers'])
        
        if not papers:
            raise HTTPException(status_code=400, detail="No papers in knowledge base")
        
        # Generate insights only
        insights = await generate_insights_analysis(kb_id, papers, kb_result.data[0]['name'])
        
        # Update only insights in database
        analysis_result = supabase.table('knowledge_base_analysis').select('*').eq('knowledge_base_id', str(kb_id)).execute()
        
        if analysis_result.data:
            # Update existing record
            supabase.table('knowledge_base_analysis').update({
                'insights': insights,
                'updated_at': datetime.now().isoformat()
            }).eq('knowledge_base_id', str(kb_id)).execute()
        else:
            # Create new record with just insights
            supabase.table('knowledge_base_analysis').insert({
                'knowledge_base_id': str(kb_id),
                'connections': {},
                'insights': insights,
                'analytics': {},
                'generated_by': 'llama-4',
                'created_at': datetime.now().isoformat()
            }).execute()
        
        return insights
        
    except Exception as e:
        print(f"Error generating insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate insights")

@router.post("/{kb_id}/generate-analytics")
async def generate_knowledgebase_analytics_endpoint(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Generate only analytics analysis for a knowledge base"""
    try:
        supabase = get_supabase()
        
        # Check access and get papers
        kb_result = supabase.table('knowledge_bases').select('user_id, name').eq('id', str(kb_id)).execute()
        if not kb_result.data or kb_result.data[0]['user_id'] != str(user_id):
            raise HTTPException(status_code=403, detail="Access denied")
        
        papers_result = supabase.table('knowledge_base_papers').select(
            'papers(id, title, year, citations, topics, venue)'
        ).eq('knowledge_base_id', str(kb_id)).execute()
        
        papers = []
        for item in papers_result.data:
            if item.get('papers'):
                papers.append(item['papers'])
        
        if not papers:
            raise HTTPException(status_code=400, detail="No papers in knowledge base")
        
        # Generate analytics only
        analytics = await generate_analytics_analysis(kb_id, papers, kb_result.data[0]['name'])
        
        # Update only analytics in database
        analysis_result = supabase.table('knowledge_base_analysis').select('*').eq('knowledge_base_id', str(kb_id)).execute()
        
        if analysis_result.data:
            # Update existing record
            supabase.table('knowledge_base_analysis').update({
                'analytics': analytics,
                'updated_at': datetime.now().isoformat()
            }).eq('knowledge_base_id', str(kb_id)).execute()
        else:
            # Create new record with just analytics
            supabase.table('knowledge_base_analysis').insert({
                'knowledge_base_id': str(kb_id),
                'connections': {},
                'insights': {},
                'analytics': analytics,
                'generated_by': 'llama-4',
                'created_at': datetime.now().isoformat()
            }).execute()
        
        return analytics
        
    except Exception as e:
        print(f"Error generating analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate analytics")

@router.get("/{kb_id}/insights")
async def get_knowledgebase_insights(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get insights tab data for a knowledge base"""
    try:
        analysis = await _get_kb_analysis(kb_id, user_id)
        if not analysis:
            return None
        return analysis.get('insights', {})
    except Exception as e:
        print(f"Error fetching insights: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch insights")

@router.get("/{kb_id}/connections")
async def get_knowledgebase_connections(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get connections graph data for a knowledge base"""
    try:
        analysis = await _get_kb_analysis(kb_id, user_id)
        if not analysis:
            return None
        return analysis.get('connections', {})
    except Exception as e:
        print(f"Error fetching connections: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch connections")

@router.get("/{kb_id}/analytics")
async def get_knowledgebase_analytics(
    kb_id: UUID,
    user_id: UUID = Depends(get_current_user_id)
):
    """Get analytics data for a knowledge base"""
    try:
        analysis = await _get_kb_analysis(kb_id, user_id)
        if not analysis:
            return None
        return analysis.get('analytics', {})
    except Exception as e:
        print(f"Error fetching analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch analytics")

async def _get_kb_analysis(kb_id: UUID, user_id: UUID):
    """Helper to get KB analysis with access check"""
    supabase = get_supabase()
    
    # Check access
    kb_result = supabase.table('knowledge_bases').select('user_id, is_public').eq('id', str(kb_id)).execute()
    
    if not kb_result.data:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    kb_info = kb_result.data[0]
    
    if (kb_info['user_id'] != str(user_id) and not kb_info['is_public']):
        share_result = supabase.table('knowledge_base_shares').select('id').eq('knowledge_base_id', str(kb_id)).eq('shared_with_user_id', str(user_id)).execute()
        if not share_result.data:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Get analysis from knowledge_base_analysis table
    analysis_result = supabase.table('knowledge_base_analysis').select('*').eq('knowledge_base_id', str(kb_id)).execute()
    
    if not analysis_result.data:
        return None  # Frontend will trigger generation
    
    return analysis_result.data[0]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def log_activity(user_id: UUID, activity_type: str, entity_type: str, entity_id: UUID, metadata: dict = None):
    """Log user activity"""
    try:
        supabase = get_supabase()
        supabase.rpc('log_user_activity', {
            'p_user_id': str(user_id),
            'p_activity_type': activity_type,
            'p_entity_type': entity_type,
            'p_entity_id': str(entity_id),
            'p_metadata': json.dumps(metadata or {})
        }).execute()
    except Exception as e:
        print(f"Error logging activity: {e}")

async def generate_insights_background(kb_id: UUID, papers: list, kb_name: str):
    """Background task to generate AI insights"""
    try:
        llama_client = LlamaClient()
        
        # Prepare papers summary for AI analysis
        papers_summary = []
        for paper in papers[:10]:  # Limit to 10 papers for analysis
            papers_summary.append({
                'title': paper['title'],
                'abstract': paper.get('abstract', ''),
                'topics': paper.get('topics', []),
                'year': paper.get('year'),
                'citations': paper.get('citations', 0)
            })
        
        # Generate insights using AI
        prompt = f"""
        Analyze this collection of research papers in the knowledge base "{kb_name}" and provide insights:
        
        Papers: {json.dumps(papers_summary, indent=2)}
        
        Please provide a JSON response with:
        1. "insights": Array of key insights about the research area
        2. "trends": Array of emerging trends identified
        3. "research_gaps": Array of identified research gaps
        4. "key_connections": Array of important connections between papers
        
        Focus on academic rigor and actionable insights.
        """
        
        response = await llama_client.generate_response(prompt)
        
        # Parse AI response
        try:
            insights_data = json.loads(response)
        except:
            # Fallback if JSON parsing fails
            insights_data = {
                "insights": ["AI analysis completed"],
                "trends": ["Emerging research patterns identified"],
                "research_gaps": ["Areas for future research identified"],
                "key_connections": ["Cross-paper relationships mapped"]
            }
        
        # Save insights to database
        supabase = get_supabase()
        supabase.table('knowledge_base_insights').insert({
            'knowledge_base_id': str(kb_id),
            'insights': insights_data.get('insights', []),
            'trends': insights_data.get('trends', []),
            'research_gaps': insights_data.get('research_gaps', []),
            'key_connections': insights_data.get('key_connections', []),
            'generated_by': 'llama-4'
        }).execute()
        
    except Exception as e:
        print(f"Error generating insights in background: {e}") 

async def generate_kb_analysis_background(kb_id: str, paper_ids: list, kb_name: str, user_id: str):
    """Background task to generate analysis for a new knowledge base"""
    try:
        supabase = get_supabase()
        
        # Get full paper data
        papers = []
        for paper_id in paper_ids:
            paper_result = supabase.table('papers').select('*').eq('id', paper_id).execute()
            if paper_result.data:
                papers.append(paper_result.data[0])
        
        if papers:
            # Generate analysis
            await generate_kb_analysis(UUID(kb_id), papers, kb_name)
            print(f"Generated analysis for knowledge base {kb_id}")
    except Exception as e:
        print(f"Error generating analysis in background for KB {kb_id}: {e}")

async def generate_kb_analysis(kb_id: UUID, papers: list, kb_name: str):
    """Generate analysis data for all tabs by calling individual generators"""
    try:
        # Generate each type of analysis separately
        connections = await generate_connections_analysis(kb_id, papers, kb_name)
        insights = await generate_insights_analysis(kb_id, papers, kb_name)
        analytics = await generate_analytics_analysis(kb_id, papers, kb_name)
        
        # Store all analysis in database
        supabase = get_supabase()
        supabase.table('knowledge_base_analysis').upsert({
            'knowledge_base_id': str(kb_id),
            'connections': connections,
            'insights': insights,
            'analytics': analytics,
            'generated_by': 'llama-4',
            'created_at': datetime.now().isoformat()
        }, on_conflict='knowledge_base_id').execute()
        
        return {
            'connections': connections,
            'insights': insights,
            'analytics': analytics
        }
        
    except Exception as e:
        print(f"Error generating KB analysis: {e}")
        return generate_fallback_analysis(papers, kb_name)

async def generate_connections_analysis(kb_id: UUID, papers: list, kb_name: str):
    """Generate connections graph data with focused prompt"""
    try:
        llama_client = LlamaClient()
        
        # Validate input
        if not papers:
            print("No papers provided for connection analysis")
            return 
        
        # Prepare paper data for connections (now includes full_text)
        papers_data = []
        for paper in papers[:20]:  # Limit to 20 papers for performance
            if not isinstance(paper, dict):
                print(f"Invalid paper data format: {paper}")
                continue
            papers_data.append({
                'id': str(paper.get('id', '')),
                'title': str(paper.get('title', ''))[:100],
                'authors': paper.get('authors', [])[:3],
                'year': paper.get('year', 2020),
                'citations': int(paper.get('citations', 0)),
                'topics': paper.get('topics', [])[:5],
                'abstract': str(paper.get('abstract', ''))[:200],
                'full_text': str(paper.get('full_text', ''))  # Pass full_text to the model
            })
        
        if not papers_data:
            print("No valid paper data after preprocessing")
            return
        
        # Focused prompt for connections
        prompt = f"""
        Analyze and identify all possible connections between these {len(papers_data)} research papers.
        Focus specifically on finding and quantifying:

        1. Topic Connections:
        - Exact shared keywords and research themes
        - Overlapping subject areas and domains
        - Similar theoretical frameworks used

        2. Citation Relationships:
        - Direct citations between papers
        - Papers citing the same key references
        - Citation patterns showing research lineage

        3. Author Networks:
        - Co-authorship between papers
        - Authors publishing multiple papers in the set
        - Institutional collaborations

        4. Methodology Links:
        - Papers using the same research methods
        - Similar experimental designs or approaches
        - Shared datasets or evaluation metrics

        For each connection found:
        1. Assign a strength score (0.0-1.0) based on:
           - Number of shared elements
           - Significance of the connection
           - Temporal proximity of the papers
        2. Provide a clear explanation of why these papers are connected, mentioning specific shared elements, methodologies, or themes.

        Papers to analyze (full text included): {json.dumps(papers_data, indent=2)}
        """
        
        response = await llama_client.generate_response(prompt, response_format={
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "authors": {"type": "array", "items": {"type": "string"}},
                            "year": {"type": "integer"},
                            "citations": {"type": "integer"},
                            "qualityScore": {"type": "number"},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "connections": {"type": "integer"}
                        },
                        "required": ["id", "title", "authors", "year", "citations", "qualityScore", "x", "y", "connections"]
                    }
                },
                "edges": {
                    "type": "array", 
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "strength": {"type": "number"},
                            "explanation": {"type": "string"},
                            "style": {
                                "type": "object",
                                "properties": {
                                    "stroke": {"type": "string"},
                                    "strokeWidth": {"type": "number"},
                                    "strokeOpacity": {"type": "number"}
                                }
                            },
                            "animated": {"type": "boolean"}
                        },
                        "required": ["id", "source", "target", "strength", "explanation"]
                    }
                },
                "stats": {
                    "type": "object",
                    "properties": {
                        "totalNodes": {"type": "integer"},
                        "totalConnections": {"type": "integer"},
                        "avgDegree": {"type": "number"}
                    },
                    "required": ["totalNodes", "totalConnections", "avgDegree"]
                }
            },
            "required": ["nodes", "edges", "stats"]
        })
        
        if not response:
            print("Empty response from LlamaClient")
            return _generate_fallback_connections(papers)
            
        try:
            # Handle both string and object responses
            data = response if isinstance(response, dict) else json.loads(response)
            
            # Validate required fields
            if not all(key in data for key in ["nodes", "edges", "stats"]):
                print("Missing required fields in response")
                return _generate_fallback_connections(papers)
                
            return data
            
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"JSON decode error: {e}")
            print(f"Raw response: {response}")
            return _generate_fallback_connections(papers)
            
    except Exception as e:
        print(f"Error in connection analysis: {e}")
        return _generate_fallback_connections(papers)

def _generate_fallback_connections(papers: list):
    """Generate basic connections when Llama is not available"""
    llama_client = LlamaClient()
    
    # Create nodes for each paper
    nodes = []
    for i, paper in enumerate(papers[:20]):  # Limit to 20 papers
        nodes.append({
            "id": str(paper.get('id', '')),
            "title": str(paper.get('title', ''))[:100],
            "authors": paper.get('authors', [])[:3],
            "year": paper.get('year', 2020),
            "citations": int(paper.get('citations', 0)),
            "qualityScore": min(9.5, 7.0 + (paper.get('citations', 0) / 10000)),
            "x": 400 + (i % 4) * 200,  # Grid layout
            "y": 300 + (i // 4) * 150,
            "connections": 0
        })
    
    # Create basic edges between papers based on year and topics
    edges = []
    for i, node1 in enumerate(nodes):
        connections = 0
        for j, node2 in enumerate(nodes[i+1:], i+1):
            # Connect papers if they're within 2 years of each other
            year_diff = abs(node1['year'] - node2['year'])
            if year_diff <= 2:
                strength = 1.0 - (year_diff / 4)  # Strength based on year difference
                edges.append({
                    "source": node1['id'],
                    "target": node2['id'],
                    "strength": strength,
                    "explanation": f"These papers were published in {node1['year']} and {node2['year']} respectively, suggesting potential research continuity."
                })
                connections += 1
                nodes[i]['connections'] = connections
                nodes[j]['connections'] = nodes[j]['connections'] + 1
    
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "totalNodes": len(nodes),
            "totalConnections": len(edges),
            "avgDegree": len(edges) * 2 / max(len(nodes), 1)  # Each edge connects 2 nodes
        }
    }

async def generate_insights_analysis(kb_id: UUID, papers: list, kb_name: str):
    """Generate insights data with focused prompt"""
    try:
        llama_client = LlamaClient()
        
        # Prepare paper data for insights analysis
        papers_data = []
        for paper in papers[:15]:
            papers_data.append({
                'id': paper['id'],
                'title': paper['title'],
                'abstract': paper.get('abstract', '')[:500],
                'year': paper.get('year'),
                'citations': paper.get('citations', 0),
                'topics': paper.get('topics', [])
            })
        
        # Focused prompt for insights
        prompt = f"""
        Analyze these {len(papers)} papers in "{kb_name}" to identify:
        1. Research trends and evolution
        2. Research gaps and opportunities
        3. Key thematic connections
        4. Emerging research areas
        
        Papers: {json.dumps(papers_data, indent=2)}
        
        Generate insightful analysis identifying patterns, gaps, and future directions.
        Return ONLY a JSON object with this exact structure:
        {{
            "researchTrends": [
                {{
                    "id": "1",
                    "type": "trend",
                    "title": "Concise trend title",
                    "description": "Clear description of the trend",
                    "keyPapers": ["paper_id1", "paper_id2"],
                    "confidence": 0.85,
                    "citations": 12345,
                    "icon": "TrendingUp"
                }}
            ],
            "researchGaps": [
                {{
                    "id": "2", 
                    "type": "gap",
                    "title": "Gap title",
                    "description": "What's missing and why it matters",
                    "keyPapers": [],
                    "confidence": 0.75,
                    "citations": 0,
                    "icon": "Zap"
                }}
            ],
            "keyConnections": [
                {{
                    "id": "3",
                    "type": "connection",
                    "title": "Connection title",
                    "description": "How topics/papers are related",
                    "keyPapers": ["paper_id1", "paper_id2"],
                    "confidence": 0.9,
                    "citations": 5000,
                    "icon": "Link2"
                }}
            ],
            "emergingAreas": [
                {{
                    "id": "4",
                    "type": "emerging",
                    "title": "Emerging area",
                    "description": "New directions being explored",
                    "keyPapers": ["paper_id1"],
                    "confidence": 0.8,
                    "citations": 1000,
                    "icon": "Sparkles"
                }}
            ],
            "suggestedQuestions": [
                "Specific research question based on the analysis",
                "Another actionable research question"
            ]
        }}
        
        Be specific and use actual paper IDs. Identify 2-4 items per category.
        If you do not know the exact answer to field, give your best guesstimate that's reasonable. 
        """
        
        response = await llama_client.generate_response(prompt, response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "insights_analysis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "researchTrends": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "type": {"type": "string"},
                                    "title": {"type": "string"},
                                    "description": {"type": "string"},
                                    "keyPapers": {"type": "array", "items": {"type": "string"}},
                                    "confidence": {"type": "number"},
                                    "citations": {"type": "integer"},
                                    "icon": {"type": "string"}
                                },
                                "required": ["id", "type", "title", "description", "keyPapers", "confidence", "citations", "icon"]
                            }
                        },
                        "researchGaps": {"type": "array", "items": {"$ref": "#/properties/researchTrends/items"}},
                        "keyConnections": {"type": "array", "items": {"$ref": "#/properties/researchTrends/items"}},
                        "emergingAreas": {"type": "array", "items": {"$ref": "#/properties/researchTrends/items"}},
                        "suggestedQuestions": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["researchTrends", "researchGaps", "keyConnections", "emergingAreas", "suggestedQuestions"]
                }
            }
        })
        
        print(f"[LLAMA RAW RESPONSE - INSIGHTS]: {response}")
        if response:
            try:
                return json.loads(response)
            except json.JSONDecodeError as e:
                print(f"JSON decode error in insights: {e}")
                print(f"Response was: {response}")
                raise e
        else:
            print("No response from LlamaClient for insights")
            raise ValueError("Empty response from LlamaClient")
        
    except Exception as e:
        print(f"Error generating insights: {e}")
        # Return properly structured fallback data
        return {
            "researchTrends": [{
                "id": "1",
                "type": "trend",
                "title": "Research Evolution",
                "description": f"Analysis of {len(papers)} papers in {kb_name}",
                "keyPapers": [p['id'] for p in papers[:2]],
                "confidence": 0.8,
                "citations": sum(p.get('citations', 0) for p in papers),
                "icon": "TrendingUp"
            }],
            "researchGaps": [{
                "id": "2",
                "type": "gap",
                "title": "Further Research Needed",
                "description": "Opportunities for future work identified",
                "keyPapers": [],
                "confidence": 0.7,
                "citations": 0,
                "icon": "Zap"
            }],
            "keyConnections": [{
                "id": "3",
                "type": "connection",
                "title": "Thematic Connections",
                "description": "Common themes across papers",
                "keyPapers": [p['id'] for p in papers[:2]],
                "confidence": 0.75,
                "citations": sum(p.get('citations', 0) for p in papers),
                "icon": "Link2"
            }],
            "emergingAreas": [{
                "id": "4",
                "type": "emerging",
                "title": "Emerging Research",
                "description": "New directions in the field",
                "keyPapers": [papers[0]['id']] if papers else [],
                "confidence": 0.7,
                "citations": papers[0].get('citations', 0) if papers else 0,
                "icon": "Sparkles"
            }],
            "suggestedQuestions": [
                "What are the main themes in this knowledge base?",
                "How has the research evolved over time?"
            ]
        }

async def generate_analytics_analysis(kb_id: UUID, papers: list, kb_name: str):
    """Generate analytics data with focused prompt"""
    try:
        llama_client = LlamaClient()
        
        # Calculate basic stats
        total_citations = sum(p.get('citations', 0) for p in papers)
        
        # Prepare minimal data for analytics
        papers_data = []
        for paper in papers:
            papers_data.append({
                'title': paper['title'][:100],
                'year': paper.get('year'),
                'citations': paper.get('citations', 0),
                'topics': paper.get('topics', [])[:5],
                'venue': paper.get('venue', 'arXiv')
            })
        
        # Focused prompt for analytics
        prompt = f"""
        Generate statistical analytics for these {len(papers)} papers.
        Focus on quantitative analysis of themes, venues, quality, and temporal patterns.
        
        Papers summary:
        - Total papers: {len(papers)}
        - Total citations: {total_citations}
        - Papers data: {json.dumps(papers_data[:10], indent=2)}
        
        Return ONLY a JSON object with this exact structure:
        {{
            "keyThemes": [
                {{"theme": "Machine Learning", "count": 8}},
                {{"theme": "Deep Learning", "count": 6}}
            ],
            "topVenues": [
                {{"venue": "NIPS", "count": 3}},
                {{"venue": "ICML", "count": 2}}
            ],
            "qualityDistribution": [
                {{"label": "Excellent (9.5+)", "count": 2}},
                {{"label": "High (9.0+)", "count": 3}},
                {{"label": "Good (8.5+)", "count": 5}}
            ],
            "citationTrends": {{
                "totalCitations": {total_citations},
                "averageQuality": 8.7,
                "topCitedPapers": [
                    {{"title": "Paper title...", "citations": 1000}}
                ]
            }},
            "timeline": {{
                "firstPaper": 2018,
                "latestPaper": 2023,
                "timeSpan": "5 years"
            }}
        }}
        
        Extract actual themes from the papers. Be accurate with counts.
        """
        
        response = await llama_client.generate_response(prompt, response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "analytics_analysis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "keyThemes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "theme": {"type": "string"},
                                    "count": {"type": "integer"}
                                },
                                "required": ["theme", "count"]
                            }
                        },
                        "topVenues": {
                            "type": "array", 
                            "items": {
                                "type": "object",
                                "properties": {
                                    "venue": {"type": "string"},
                                    "count": {"type": "integer"}
                                },
                                "required": ["venue", "count"]
                            }
                        },
                        "qualityDistribution": {
                            "type": "array",
                            "items": {
                                "type": "object", 
                                "properties": {
                                    "label": {"type": "string"},
                                    "count": {"type": "integer"}
                                },
                                "required": ["label", "count"]
                            }
                        },
                        "citationTrends": {
                            "type": "object",
                            "properties": {
                                "totalCitations": {"type": "integer"},
                                "averageQuality": {"type": "number"},
                                "topCitedPapers": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "title": {"type": "string"},
                                            "citations": {"type": "integer"}
                                        },
                                        "required": ["title", "citations"]
                                    }
                                }
                            },
                            "required": ["totalCitations", "averageQuality", "topCitedPapers"]
                        },
                        "timeline": {
                            "type": "object",
                            "properties": {
                                "firstPaper": {"type": "integer"},
                                "latestPaper": {"type": "integer"},
                                "timeSpan": {"type": "string"}
                            },
                            "required": ["firstPaper", "latestPaper", "timeSpan"]
                        }
                    },
                    "required": ["keyThemes", "topVenues", "qualityDistribution", "citationTrends", "timeline"]
                }
            }
        })
        
        print(f"[LLAMA RAW RESPONSE - ANALYTICS]: {response}")
        if response:
            try:
                # Handle both string and dict responses
                if isinstance(response, str):
                    return json.loads(response)
                elif isinstance(response, (dict, list)):
                    return response
                else:
                    print(f"Unexpected response type: {type(response)}")
                    raise ValueError("Invalid response format")
            except json.JSONDecodeError as e:
                print(f"JSON decode error in analytics: {e}")
                print(f"Response was: {response}")
                raise e
            except Exception as e:
                print(f"Error parsing analytics response: {e}")
                raise e
        else:
            print("No response from LlamaClient for analytics")
            raise ValueError("Empty response from LlamaClient")
        
    except Exception as e:
        print(f"Error generating analytics: {e}")
        # Return computed analytics as fallback
        valid_years = [p.get('year') for p in papers if p.get('year') is not None]
        first_year = min(valid_years) if valid_years else 2020
        latest_year = max(valid_years) if valid_years else 2020
        
        return {
            "keyThemes": [],
            "topVenues": [],
            "qualityDistribution": [
                {"label": "Excellent (9.5+)", "count": 0},
                {"label": "High (9.0+)", "count": 0},
                {"label": "Good (8.5+)", "count": len(papers)}
            ],
            "citationTrends": {
                "totalCitations": sum(p.get('citations', 0) for p in papers),
                "averageQuality": 8.5,
                "topCitedPapers": sorted([{
                    "title": p['title'][:50] + "...",
                    "citations": p.get('citations', 0)
                } for p in papers], key=lambda x: x['citations'], reverse=True)[:3]
            },
            "timeline": {
                "firstPaper": first_year,
                "latestPaper": latest_year,
                "timeSpan": f"{latest_year - first_year} years"
            }
        }

def generate_fallback_analysis(papers: list, kb_name: str):
    """Generate fallback analysis structure"""
    # Calculate basic stats
    total_citations = sum(p.get('citations', 0) for p in papers)
    avg_citations = total_citations // max(len(papers), 1)
    
    # Create nodes for connections graph
    nodes = []
    for i, paper in enumerate(papers[:10]):
        nodes.append({
            "id": paper['id'],
            "title": paper['title'][:50] + "..." if len(paper['title']) > 50 else paper['title'],
            "authors": [paper.get('authors', ['Unknown'])[0]] if paper.get('authors') else ['Unknown'],
            "year": paper.get('year', 2020) or 2020,
            "citations": paper.get('citations', 0),
            "qualityScore": min(9.5, 7.0 + (paper.get('citations', 0) / 10000)),
            "x": 400 + (i % 3) * 200,
            "y": 300 + (i // 3) * 150,
            "connections": 2
        })
    
    # Get valid years (excluding None values)
    valid_years = [p.get('year') for p in papers if p.get('year') is not None]
    first_year = min(valid_years) if valid_years else 2020
    latest_year = max(valid_years) if valid_years else 2020
    time_span = latest_year - first_year
    
    return {
        "connections": {
            "nodes": nodes,
            "edges": [],
            "stats": {
                "totalNodes": len(nodes),
                "totalConnections": 0,
                "avgDegree": 0
            }
        },
        "insights": {
            "researchTrends": [{
                "id": "1",
                "type": "trend",
                "title": "Research Evolution",
                "description": f"Analysis of {len(papers)} papers in {kb_name}",
                "keyPapers": [p['id'] for p in papers[:3]],
                "confidence": 0.8,
                "citations": total_citations,
                "icon": "TrendingUp"
            }],
            "researchGaps": [{
                "id": "2",
                "type": "gap",
                "title": "Further Research Needed",
                "description": "Opportunities for future work identified",
                "keyPapers": [],
                "confidence": 0.7,
                "citations": 0,
                "icon": "Zap"
            }],
            "keyConnections": [],
            "emergingAreas": [],
            "suggestedQuestions": [
                "What are the main themes in this knowledge base?",
                "How has the research evolved over time?"
            ]
        },
        "analytics": {
            "keyThemes": [],
            "topVenues": [],
            "qualityDistribution": [
                {"label": "Excellent (9.5+)", "count": len([p for p in papers if p.get('citations', 0) > 10000])},
                {"label": "High (9.0+)", "count": len([p for p in papers if 5000 < p.get('citations', 0) <= 10000])},
                {"label": "Good (8.5+)", "count": len([p for p in papers if p.get('citations', 0) <= 5000])}
            ],
            "citationTrends": {
                "totalCitations": total_citations,
                "averageQuality": 8.5,
                "topCitedPapers": sorted([{
                    "title": p['title'][:50] + "..." if len(p['title']) > 50 else p['title'],
                    "citations": p.get('citations', 0)
                } for p in papers], key=lambda x: x['citations'], reverse=True)[:3]
            },
            "timeline": {
                "firstPaper": first_year,
                "latestPaper": latest_year,
                "timeSpan": f"{time_span} years"
            }
        }
    } 