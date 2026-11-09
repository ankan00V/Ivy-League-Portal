from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "opportunities.py"


def test_profile_semantic_search_rebuilds_stale_model_embeddings() -> None:
    source = ENDPOINT.read_text(encoding="utf-8")
    start = source.index("async def semantic_search_opportunities(")
    end = source.index("\n\n@router.get(\"/recommended/me\"", start)
    body = source[start:end]

    assert "profile_user.profile_embedding_model_version != embedding_pipeline.model_version" in body
    assert "embedding_pipeline.recompute_user_embedding(user_id=resolved_user_id, force=True)" in body
