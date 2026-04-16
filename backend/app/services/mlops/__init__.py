from __future__ import annotations

from typing import Any

__all__ = ["drift_service", "retraining_service", "mlops_alerting_service"]


def __getattr__(name: str) -> Any:
    if name == "drift_service":
        from app.services.mlops.drift_service import drift_service

        return drift_service
    if name == "retraining_service":
        from app.services.mlops.retraining_service import retraining_service

        return retraining_service
    if name == "mlops_alerting_service":
        from app.services.mlops.alerting_service import mlops_alerting_service

        return mlops_alerting_service
    raise AttributeError(name)
