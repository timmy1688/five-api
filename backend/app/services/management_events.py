from uuid import uuid4
from functools import wraps

from tortoise.transactions import in_transaction

from app.models import ManagementEvent, User
from app.services.redaction import redact


async def record_event(actor: User, action: str, target_id: int, tenant_id: int = 0,
                       detail: dict | None = None, operation_id: str | None = None):
    # Call inside the mutation's transaction. Never record passwords or raw keys.
    return await ManagementEvent.create(
        operation_id=operation_id or str(uuid4()), actor_id=actor.id,
        tenant_id=tenant_id, action=action, target_id=target_id, detail=redact(detail or {}),
    )


def audit_mutation(action: str):
    """Record platform configuration mutations atomically, without credential values."""
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            actor = next((value for value in kwargs.values() if isinstance(value, User)), None)
            async with in_transaction():
                result = await function(*args, **kwargs)
                if actor is not None:
                    target_id = next((value for name, value in kwargs.items() if name.endswith("_id") and isinstance(value, int)), 0)
                    target_id = getattr(result, "id", target_id) or (result.get("id", 0) if isinstance(result, dict) else 0)
                    body = kwargs.get("body")
                    await record_event(actor, action, target_id, detail={"fields": sorted(body.model_fields_set) if body else []})
                return result
        return wrapped
    return decorate
