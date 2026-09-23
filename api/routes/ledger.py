from __future__ import annotations

import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..deps import AppContext, call_tool, get_ctx, read_resource

router = APIRouter(tags=["ledger"])


@router.get("/overview")
async def overview(ctx: AppContext = Depends(get_ctx)) -> Any:
    # Opening the app is when a bill that came due while you were away gets filed. The run is idempotent and a
    # no-op when nothing is due, so it costs one indexed query on the common path.
    await call_tool(ctx, "run_autopay", {})
    return await call_tool(ctx, "get_overview", {})


@router.get("/recurring")
async def recurring(ctx: AppContext = Depends(get_ctx)) -> Any:
    await call_tool(ctx, "run_autopay", {})
    return await call_tool(ctx, "list_recurring", {})


class RecurringBody(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0)
    cadence: str = "monthly"
    next_due: str | None = None
    category: str | None = None
    autopay: bool = False


@router.post("/recurring", status_code=201)
async def add_recurring(body: RecurringBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "add_recurring", body.model_dump(exclude_none=True))


class AutopayBody(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    active: bool = True
    amount: float | None = Field(default=None, gt=0)
    next_due: str | None = None


@router.post("/recurring/autopay")
async def set_autopay(body: AutopayBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "set_autopay", body.model_dump(exclude_none=True))


@router.post("/recurring/autopay/clear")
async def clear_autopay(body: AutopayBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "clear_autopay", {"merchant": body.merchant})


@router.post("/recurring/autopay/run")
async def run_autopay(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "run_autopay", {})


@router.get("/activity")
async def activity(limit: int = Query(30, ge=1, le=200), offset: int = Query(0, ge=0), ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "recent_activity", {"limit": limit, "offset": offset})


class GoalBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target: float = Field(gt=0)
    saved: float | None = Field(default=None, ge=0)
    due: str | None = None
    icon: str | None = Field(default=None, max_length=8)


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target: float | None = Field(default=None, gt=0)
    saved: float | None = Field(default=None, ge=0)
    due: str | None = None
    icon: str | None = Field(default=None, max_length=8)


class EmiBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0)
    start_date: str
    tenure_months: int = Field(ge=1, le=480)
    lender: str | None = Field(default=None, max_length=80)
    principal: float | None = Field(default=None, gt=0)


class GoalAdd(BaseModel):
    amount: float


@router.get("/goals")
async def goals(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "list_goals", {})


@router.post("/goals", status_code=201)
async def create_goal(body: GoalBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "upsert_goal", body.model_dump(exclude_none=True))


@router.patch("/goals/{goal_id}")
async def update_goal(goal_id: int, body: GoalPatch, ctx: AppContext = Depends(get_ctx)) -> Any:
    current = await call_tool(ctx, "list_goals", {})
    existing = next((g for g in current["goals"] if g["id"] == goal_id), None)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(404, "Goal not found")
    args = {"goal_id": goal_id, "name": body.name or existing["name"], "target": body.target or existing["target"]}
    for k in ("saved", "due", "icon"):
        v = getattr(body, k)
        if v is not None:
            args[k] = v
    return await call_tool(ctx, "upsert_goal", args)


@router.get("/emis")
async def emis(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "list_emis", {})


@router.post("/emis", status_code=201)
async def create_emi(body: EmiBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "upsert_emi", body.model_dump(exclude_none=True))


@router.put("/emis/{emi_id}")
async def update_emi(emi_id: int, body: EmiBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "upsert_emi", {**body.model_dump(exclude_none=True), "emi_id": emi_id})


@router.delete("/emis/{emi_id}")
async def delete_emi(emi_id: int, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "delete_emi", {"emi_id": emi_id})


@router.post("/goals/{goal_id}/add")
async def add_to_goal(goal_id: int, body: GoalAdd, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "add_to_goal", {"goal_id": goal_id, "amount": body.amount})


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "delete_goal", {"goal_id": goal_id})


@router.get("/export.csv")
async def export_csv(period: str | None = None, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    """Every transaction (or a period) as CSV, fetched page by page through the MCP tool."""
    async def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "date", "amount", "direction", "currency", "merchant", "description", "category", "source", "client", "needs_review"])
        yield buf.getvalue()
        offset = 0
        while True:
            args: dict[str, Any] = {"limit": 500, "offset": offset, "order": "date_asc"}
            if period:
                args["period"] = period
            page = await call_tool(ctx, "list_transactions", args)
            buf = io.StringIO()
            w = csv.writer(buf)
            for t in page["transactions"]:
                w.writerow([t["id"], t["date"], t["amount"], t["direction"], t["currency"], t["merchant"], t["description"] or "",
                            t["category"] or "", t["source"], t["client"] or "", "yes" if t["needs_review"] else ""])
            yield buf.getvalue()
            offset += page["count"]
            if page["count"] == 0 or offset >= page["total"]:
                break

    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="finmcp-transactions.csv"'})


@router.get("/status")
async def status(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await read_resource(ctx, "finmcp://status")


@router.get("/transactions")
async def list_transactions(
    ctx: AppContext = Depends(get_ctx),
    period: str | None = None, start_date: str | None = None, end_date: str | None = None,
    category: str | None = None, merchant: str | None = None, search: str | None = None,
    direction: Literal["debit", "credit"] | None = None, min_amount: float | None = None, max_amount: float | None = None,
    uncategorized_only: bool = False, needs_review_only: bool = False,
    order: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc",
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
) -> Any:
    args = {k: v for k, v in dict(period=period, start_date=start_date, end_date=end_date, category=category, merchant=merchant,
                                    search=search, direction=direction, min_amount=min_amount, max_amount=max_amount).items() if v not in (None, "")}
    args.update(uncategorized_only=uncategorized_only, needs_review_only=needs_review_only, order=order, limit=limit, offset=offset)
    return await call_tool(ctx, "list_transactions", args)


class NewTransaction(BaseModel):
    date: str
    amount: float = Field(gt=0)
    merchant: str = Field(min_length=1)
    direction: Literal["debit", "credit"] = "debit"
    description: str | None = None
    category: str | None = None
    source: str = "api"
    ask_if_unsure: bool = True


class EntryText(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    merchant: str | None = None


@router.post("/transactions/parse")
async def parse_entry(body: EntryText, ctx: AppContext = Depends(get_ctx)) -> Any:
    """What the quick-add card asks when its own reading of a line is only a guess. Read-only, and cached per line."""
    return await call_tool(ctx, "parse_entry", body.model_dump(exclude_none=True))


@router.post("/transactions", status_code=201)
async def add_transaction(body: NewTransaction, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "add_transaction", body.model_dump(exclude_none=True))


class TransactionPatch(BaseModel):
    date: str | None = None
    amount: float | None = Field(default=None, gt=0)
    merchant: str | None = None
    description: str | None = None
    direction: Literal["debit", "credit"] | None = None
    category: str | None = None
    needs_review: bool | None = None


@router.patch("/transactions/{transaction_id}")
async def update_transaction(transaction_id: int, body: TransactionPatch, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "update_transaction", {"transaction_id": transaction_id, **body.model_dump(exclude_none=True)})


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: int, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "delete_transaction", {"transaction_id": transaction_id, "confirmed": True})


@router.post("/transactions/{transaction_id}/categorize")
async def categorize(transaction_id: int, force: bool = False, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "categorize_transaction", {"transaction_id": transaction_id, "force": force})


@router.post("/transactions/categorize-uncategorized")
async def categorize_uncategorized(limit: int = Query(25, ge=1, le=200), ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "categorize_uncategorized", {"limit": limit})


@router.get("/categories")
async def categories(ctx: AppContext = Depends(get_ctx)) -> Any:
    return await read_resource(ctx, "finmcp://categories")


class BudgetBody(BaseModel):
    monthly_limit: float | None = Field(default=None, ge=0)


@router.put("/categories/{name}/budget")
async def set_budget(name: str, body: BudgetBody, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "set_budget", {"category": name, "monthly_limit": body.monthly_limit})


@router.get("/summary")
async def summary(period: str = "this month", group_by: Literal["category", "merchant", "day", "week", "month"] = "category",
                  top: int = Query(15, ge=1, le=100), ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "get_summary", {"period": period, "group_by": group_by, "top": top})


@router.get("/trends")
async def trends(months: int = Query(6, ge=2, le=24), top: int = Query(8, ge=1, le=30), ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "get_trends", {"months": months, "top": top})


@router.get("/budget")
async def budget(month: str | None = None, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "get_budget_summary", {"month": month} if month else {})


@router.get("/alerts")
async def alerts(month: str | None = None, ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "check_budget_alerts", {"month": month} if month else {})


@router.get("/query")
async def query(question: str = Query(min_length=3), limit: int = Query(200, ge=1, le=1000), ctx: AppContext = Depends(get_ctx)) -> Any:
    return await call_tool(ctx, "query_transactions", {"question": question, "limit": limit})
