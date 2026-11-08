import asyncio
from unittest.mock import AsyncMock, PropertyMock, patch

import numpy as np
import pytest

from app.core.time import utc_now
from app.services import vector_service as vector_service_module
from app.services.vector_service import OpportunityVectorService


@pytest.fixture
def service() -> OpportunityVectorService:
    instance = OpportunityVectorService()
    instance._last_build_at = utc_now()
    instance._model_version = "old-model"
    instance._vectors = np.asarray([[1.0, 0.0]], dtype=np.float32)
    instance._metas = [{"id": "legacy", "title": "Legacy vector"}]
    return instance


def test_ready_index_requires_current_embedding_model_version(service: OpportunityVectorService) -> None:
    with patch.object(
        type(vector_service_module.embedding_pipeline),
        "model_version",
        new_callable=PropertyMock,
        return_value="new-model",
    ):
        assert not service.is_ready()


def test_search_never_scores_a_stale_model_index(service: OpportunityVectorService) -> None:
    async def run_search() -> list[dict]:
        with patch.object(
            type(vector_service_module.embedding_pipeline),
            "model_version",
            new_callable=PropertyMock,
            return_value="new-model",
        ), patch.object(service, "_ensure_index", AsyncMock()):
            return await service.search_by_vector(np.asarray([1.0, 0.0], dtype=np.float32))

    assert asyncio.run(run_search()) == []


def test_rebuild_does_not_short_circuit_after_a_model_change(service: OpportunityVectorService) -> None:
    class CountQuery:
        async def count(self) -> int:
            return 1

    async def run_rebuild() -> None:
        with patch.object(
            type(vector_service_module.embedding_pipeline),
            "model_version",
            new_callable=PropertyMock,
            return_value="new-model",
        ), patch.object(
            vector_service_module.Opportunity,
            "find_many",
            return_value=CountQuery(),
        ), patch.object(
            vector_service_module,
            "_load_opportunities_paged",
            AsyncMock(return_value=[]),
        ):
            await service.rebuild()

    asyncio.run(run_rebuild())
    assert service._model_version == "new-model"
