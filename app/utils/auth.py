"""
Authentication utilities for DataEngineX
"""

from fastapi import HTTPException, Header
from typing import Optional
from uuid import UUID
import os
from ..utils.supabase_client import get_supabase
from ..models.research_models import UserContext

async def get_current_user_id(x_user_id: Optional[str] = Header(None, alias="X-User-ID")) -> UUID:
    """Extract user ID from X-User-ID header (simplified approach)"""
    print(f"DEBUG: get_current_user_id called with x_user_id header: {x_user_id}")
    user_context = await get_current_user(x_user_id)
    print(f"DEBUG: Extracted user_id: {user_context.user_id}")
    return user_context.user_id

async def get_current_user(x_user_id: Optional[str] = Header(None, alias="X-User-ID")) -> UserContext:
    """Extract user context from X-User-ID header (simplified approach)"""
    print(f"DEBUG: get_current_user called with x_user_id header: {x_user_id}")
    
    if not x_user_id:
        # Demo mode - use demo user
        print("DEBUG: No X-User-ID header found, using demo user")
        return UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            email="demo@dataenginex.com",
            full_name="Demo User"
        )
    
    try:
        # Use the provided user ID directly
        user_context = UserContext(
            user_id=UUID(x_user_id),
            email=f"user-{x_user_id}@delphix.com",
            full_name="DelphiX User"
        )
        print(f"DEBUG: Created user context for user_id: {user_context.user_id}")
        return user_context
    except Exception as e:
        # For development/demo purposes, fallback to demo mode
        print(f"DEBUG: Error parsing user ID {x_user_id}, falling back to demo user: {e}")
        return UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            email="demo@dataenginex.com", 
            full_name="Demo User"
        ) 