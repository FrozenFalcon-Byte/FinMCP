from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..deps import AppContext, call_tool, get_ctx, read_resource

router = APIRouter(tags=["imports"])
MAX_UPLOAD = 25 * 1024 * 1024
KINDS = ("auto", "receipt", "statement", "csv", "sms")


async def _save(ctx: AppContext, file: UploadFile) -> str:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file larger than 25 MB")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "upload")[:80]
    path = ctx.upload_dir / f"{uuid.uuid4().hex[:8]}_{safe}"
    path.write_bytes(data)
    return str(path)


@router.post("/import/preview")
async def preview(file: UploadFile = File(...), kind: str = Form("auto"), ctx: AppContext = Depends(get_ctx)) -> Any:
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    path = await _save(ctx, file)
    result = await call_tool(ctx, "parse_statement", {"file_path": path, "kind": kind})
    result["upload_path"] = path
    return result


@router.post("/import")
async def import_file(file: UploadFile | None = File(None), upload_path: str | None = Form(None), kind: str = Form("auto"),
                      auto_categorize: bool = Form(True), dry_run: bool = Form(False), ctx: AppContext = Depends(get_ctx)) -> Any:
    if kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    if upload_path:
        if not upload_path.startswith(str(ctx.upload_dir)):
            raise HTTPException(400, "upload_path must come from /import/preview")
        path = upload_path
    elif file is not None:
        path = await _save(ctx, file)
    else:
        raise HTTPException(400, "send a file or an upload_path")
    return await call_tool(ctx, "import_statement", {"file_path": path, "kind": kind, "auto_categorize": auto_categorize, "dry_run": dry_run})


class TextImport(BaseModel):
    text: str = Field(min_length=10, max_length=200000)
    kind: Literal["sms", "csv"] = "sms"
    source_name: str | None = None
    dry_run: bool = False
    auto_categorize: bool = True


@router.post("/import/text")
async def import_text(body: TextImport, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "import_text", body.model_dump(exclude_none=True))


@router.get("/imports")
async def recent_imports(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await read_resource(ctx, "finmcp://imports/recent")
