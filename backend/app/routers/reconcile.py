from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models import User
from app.services.auth import require_permission
from app.services.reconcile import read_csv, reconcile_bill, resolve_mapping

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])

MAX_BYTES = 10 * 1024 * 1024


@router.post("")
async def reconcile(
    file: UploadFile = File(...),
    date_column: str = Form(""),
    cost_column: str = Form(""),
    model_column: str = Form(""),
    channel_ids: str = Form(""),
    utc_offset: int = Form(0, ge=-12, le=14),
    _: User = require_permission("stat:read"),
):
    """Empty column names are guessed. model_column "-" compares per day only."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV larger than 10 MB")
    columns, rows = read_csv(data)
    if not columns:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    ids = [int(part) for part in channel_ids.split(",") if part.strip().isdigit()]
    mapping = resolve_mapping(columns, date_column, cost_column, model_column)
    return await reconcile_bill(columns, rows, mapping, ids, utc_offset)
