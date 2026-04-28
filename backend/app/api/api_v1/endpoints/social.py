from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from beanie import PydanticObjectId

from app.api.deps import get_current_active_user
from app.models.post import Post, Comment
from app.models.user import User

router = APIRouter()

class PostCreate(BaseModel):
    domain: str
    content: str

class PostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: PydanticObjectId
    user_id: PydanticObjectId
    domain: str
    content: str
    likes_count: int
    created_at: datetime
    
class CommentCreate(BaseModel):
    content: str

class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: PydanticObjectId
    post_id: PydanticObjectId
    user_id: PydanticObjectId
    content: str
    created_at: datetime


@router.get("/posts", response_model=list[PostResponse])
async def read_posts(
    skip: int = 0, limit: int = 50, domain: Optional[str] = None
) -> Any:
    safe_limit = max(1, min(limit, 100))
    if domain:
        posts = await Post.find_many(Post.domain == domain).sort("-created_at").skip(skip).limit(safe_limit).to_list()
    else:
        posts = await Post.find_many().sort("-created_at").skip(skip).limit(safe_limit).to_list()
    return posts

@router.post("/posts", response_model=PostResponse)
async def create_post(
    post_in: PostCreate,
    current_user: User = Depends(get_current_active_user)
) -> Any:
    post = Post(
        user_id=current_user.id,
        domain=post_in.domain,
        content=post_in.content
    )
    await post.insert()
    return post

@router.post("/posts/{id}/like")
async def like_post(
    id: PydanticObjectId,
    current_user: User = Depends(get_current_active_user)
) -> Any:
    post = await Post.get(id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.likes_count += 1
    await post.save()
    return {"message": "Post liked", "likes_count": post.likes_count}


@router.get("/posts/{id}/comments", response_model=list[CommentResponse])
async def list_post_comments(id: PydanticObjectId) -> Any:
    post = await Post.get(id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return await Comment.find(Comment.post_id == id).sort("-created_at").to_list()


@router.post("/posts/{id}/comments", response_model=CommentResponse)
async def create_post_comment(
    id: PydanticObjectId,
    comment_in: CommentCreate,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    post = await Post.get(id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    comment = Comment(post_id=id, user_id=current_user.id, content=comment_in.content)
    await comment.insert()
    return comment
