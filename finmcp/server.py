"""FinMCP: the MCP server. One server can serve one bound account (in-process, stdio) or many accounts (the
remote Streamable HTTP endpoint, where every request carries a bearer token and the principal rides on the request).

Why MCP? The ledger's brain (categorisation, budgets, recurring detection, statement parsing, guarded SQL) is written
once, as tools. The web app, the in-app assistant, Claude Desktop, Claude Code and any other MCP host call the same
tools with the same rules, the same audit trail and the same row-level isolation.

The server uses the whole protocol, not just tools:
- resources + `subscriptions/listen`: clients subscribe to `finmcp://overview` and learn about every write, whoever made it
- sampling: when the client offers a model, categorisation runs through `sampling/createMessage`; the server holds no API key
- elicitation: unsure where to file a transaction, the server asks the person; deletes ask for confirmation
- progress and logging notifications for long-running tools; roots decide which files may be imported
- prompts and argument completion for the workflows an assistant should run
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import json
import logging
import threading
from collections.abc import Callable
from datetime import date as _date
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlparse

import anyio
import mcp.types as mt
from mcp.server.mcpserver import AcceptedElicitation, Context, Elicit, ElicitationResult, MCPServer, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import ListRoots, Sample
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, create_model

from . import __version__
from .config import Settings, load_settings
from .db import Database, database_for
from .db.repository import Repository, Transaction
from .db.seed import seed_demo_data
from .ingestion.importer import Importer
from .llm.prompts import schema_doc
from .llm.provider import SAMPLING_SYSTEM, LLMProvider, RuleBasedProvider, SampledProvider, get_provider, parse_sampled, sampling_prompt
from .services.categorize import NEEDS_REVIEW_BELOW, Categorizer
from .services.emis import emi_report, emi_status
from .services.entry import parse_entry as read_entry_line
from .services.overview import get_overview
from .services.periods import resolve_period
from .services.recurring import list_recurring
from .services.summary import check_budget_alerts, get_budget_summary, get_summary
from .services.text_to_sql import QueryService
from .subscriptions import RoutedBus
from .taxonomy import resolve_category_name, seed_categories

log = logging.getLogger("finmcp.server")

INSTRUCTIONS = """FinMCP is a personal-finance server. It owns one account's ledger of transactions, a category taxonomy
with monthly budgets, savings goals, and the history of what every connected app did.

Conventions
- Amounts are positive numbers; `direction` says whether money went out ('debit') or came in ('credit').
- Spending excludes categories of kind 'transfer' (Investments, Transfers), which move money rather than consume it.
- Periods accept 'this month', 'last month', 'last 30 days', 'YYYY-MM', 'august 2026', 'ytd', 'YYYY-MM-DD..YYYY-MM-DD'.

How to work
- Start with get_overview for "how am I doing": spend, pace, safe-to-spend, upcoming bills, alerts, goals.
- For "how much / top / breakdown" questions prefer get_summary (fast, exact) and get_budget_summary for budgets.
- list_recurring finds subscriptions and bills with their next due date.
- For anything the summaries cannot express, use query_transactions (natural language) or run_sql (read-only
  PostgreSQL SELECT on v_transactions; read the finmcp://schema resource first).
- add_transaction auto-categorizes. If your client offers sampling, the server uses your model for it; if it offers
  elicitation, the server may ask the person which category to use when unsure.
- When the user corrects a category, call update_transaction with `category`; the merchant is remembered.
- delete_transaction asks for confirmation through elicitation unless confirmed=true.
- Subscribe to finmcp://overview (subscriptions/listen) to be told when anything changes.
- Every write is recorded with the name of the client that made it (recent_activity shows the trail).
"""

READ = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
SKIP = "(leave for review)"

_seeded_users: set[str] = set()
_seed_lock = threading.Lock()

# Set by the API's bearer-token middleware for the multi-account HTTP endpoint. The MCP SDK carries the sender's
# context variables with every message, so tools, resources and the subscription bus see the request's principal.
current_principal: contextvars.ContextVar[Any] = contextvars.ContextVar("finmcp_principal", default=None)


class Confirm(BaseModel):
    confirm: bool = Field(default=False, description="Yes, go ahead")


class BudgetLine(BaseModel):
    """One line of a budget list: a category and what it is allowed each month."""

    category: str = Field(min_length=1, max_length=60)
    monthly_limit: float = Field(ge=0)


class TenantState:
    """One account as seen by one client: repository, categorizer, query service, importer."""

    def __init__(self, db: Database, settings: Settings, provider: LLMProvider, user_id: str, client: str, currency: str):
        self.settings = settings
        self.user_id = user_id
        self.client = client
        self.currency = currency
        self.repo = Repository(db, user_id, client=client)
        with _seed_lock:
            if user_id not in _seeded_users:
                seed_categories(self.repo)
                _seeded_users.add(user_id)
        self.provider = provider
        self.categorizer = Categorizer(self.repo, provider, actor="mcp")
        self.queries = QueryService(self.repo, provider, currency)
        self.importer = Importer(self.repo, self.categorizer, provider)

    def categorizer_with(self, sampled: mt.CreateMessageResult | None, items: list[dict[str, Any]]) -> Categorizer:
        """The client's model (its sampled answers) when the client offered sampling, otherwise the server's provider."""
        if sampled is None:
            return self.categorizer
        return Categorizer(self.repo, SampledProvider(parse_sampled(_text_of(sampled), items)), actor="mcp")


class ServerState:
    """Shared by every request the server handles: the database, the model provider and the tenant cache."""

    def __init__(self, settings: Settings, *, db: Database | None = None, user_id: str | None = None, client: str | None = None,
                 currency: str | None = None):
        self.settings = settings
        self._db = db
        self.fixed_user_id = user_id
        self.fixed_client = client
        self.currency = currency or settings.currency
        self.provider: LLMProvider = get_provider(settings)
        self.tenants: dict[tuple[str, str], TenantState] = {}
        self._lock = threading.Lock()

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = database_for(self.settings)
        return self._db

    def user_for(self, ctx: Context | None = None) -> str | None:
        if self.fixed_user_id:
            return self.fixed_user_id
        principal = _principal_from(ctx)
        return getattr(principal, "user_id", None) if principal is not None else None

    def tenant(self, ctx: Context | None = None) -> TenantState:
        user_id = self.user_for(ctx)
        if user_id is None:
            raise ToolError("Unauthenticated: this endpoint needs a bearer token (create one under MCP in the app).")
        client = self.fixed_client or _client_name(ctx) or "mcp"
        key = (user_id, client)
        st = self.tenants.get(key)
        if st is None:
            with self._lock:
                st = self.tenants.get(key)
                if st is None:
                    st = TenantState(self.db, self.settings, self.provider, user_id, client, self._currency_for(user_id))
                    self.tenants[key] = st
        return st

    def _currency_for(self, user_id: str) -> str:
        try:
            with self.db.admin() as conn:
                row = conn.execute("SELECT currency FROM profiles WHERE id = %s", (user_id,)).fetchone()
            return str(row["currency"]) if row and row.get("currency") else self.currency
        except Exception:  # noqa: BLE001 - a missing profile is not an error for the ledger
            return self.currency

    def forget(self, user_id: str) -> None:
        with self._lock:
            for key in [k for k in self.tenants if k[0] == user_id]:
                self.tenants.pop(key, None)


# ---------------------------------------------------------------------- request helpers


def _principal_from(ctx: Context | None) -> Any:
    principal = current_principal.get()
    if principal is not None:
        return principal
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
    except ValueError:
        return None
    state = getattr(request, "state", None)
    return getattr(state, "principal", None)


def _client_name(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        params = ctx.request_context.session.client_params
    except (ValueError, AttributeError):
        return None
    info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    return str(name)[:60] if name else None


def _client_can(ctx: Context | None, what: Literal["sampling", "elicitation", "roots"]) -> bool:
    """Does the client on this request offer a client-side capability?"""
    if ctx is None:
        return False
    try:
        caps = ctx.client_capabilities
    except (ValueError, AttributeError):
        return False
    if caps is None:
        return False
    return getattr(caps, what, None) is not None


def _text_of(result: mt.CreateMessageResult) -> str:
    content = result.content if isinstance(result.content, list) else [result.content]
    return "\n".join(str(getattr(c, "text", "") or "") for c in content)


# ---------------------------------------------------------------------- resolvers
# Server-to-client requests (sampling, elicitation, roots) are declared as resolvers: the SDK runs them before the
# tool body and, on protocol 2026-07-28, batches their questions into an `input_required` result that the client
# answers before retrying the call; on older revisions it sends each as a standalone request mid-call. A resolver
# that returns a plain value asks nothing, which keeps every question optional and gated on the client's capabilities.

_RULES = RuleBasedProvider()


def _tenant(ctx: Context) -> TenantState:
    return ctx.mcp_server.finmcp.tenant(ctx)  # type: ignore[attr-defined]


def _rule_guess(st: TenantState, merchant: str, description: str | None, direction: str) -> Any:
    """What memory and keyword rules alone would say, without any model."""
    probe = SimpleNamespace(merchant=merchant, description=description, direction=direction, amount=0.0)
    return Categorizer(st.repo, _RULES).guess(probe)  # type: ignore[arg-type]


def _item(tx: Any) -> dict[str, Any]:
    return {"merchant": tx.merchant, "description": tx.description, "amount": tx.amount, "direction": tx.direction}


def _sample_for(st: TenantState, items: list[dict[str, Any]]) -> Sample:
    user = sampling_prompt(items, st.repo.list_categories(), st.repo.memory_examples(20))
    return Sample([mt.SamplingMessage(role="user", content=mt.TextContent(type="text", text=user))], max_tokens=200 + 90 * len(items),
                  system_prompt=SAMPLING_SYSTEM, temperature=0.0, model_preferences=mt.ModelPreferences(hints=[mt.ModelHint(name="claude")]))


def _valid_iso(value: str) -> bool:
    try:
        _parse_iso(value)
    except ValueError:
        return False
    return True


def _add_sample(ctx: Context, date: str, merchant: str, description: str | None, direction: str, amount: float, category: str | None,
                auto_categorize: bool) -> Sample | None:
    """add_transaction: borrow the client's model when memory and rules have no answer. Invalid input asks nothing:
    the tool body rejects it."""
    if category or not auto_categorize or not _valid_iso(date) or not _client_can(ctx, "sampling"):
        return None
    st = _tenant(ctx)
    if _rule_guess(st, merchant, description, direction).category:
        return None
    return _sample_for(st, [{"merchant": merchant, "description": description, "amount": amount, "direction": direction}])


def _add_question(ctx: Context, date: str, merchant: str, description: str | None, direction: str, amount: float,
                  category: str | None, auto_categorize: bool, ask_if_unsure: bool,
                  sampled: Annotated[mt.CreateMessageResult | None, Resolve(_add_sample)]) -> Elicit[Any] | None:
    """add_transaction: ask the person where to file it when the best guess is weak."""
    if category or not auto_categorize or not ask_if_unsure or not _valid_iso(date) or not _client_can(ctx, "elicitation"):
        return None
    st = _tenant(ctx)
    guess = _rule_guess(st, merchant, description, direction)
    name, confidence = guess.category, guess.confidence
    if not name and sampled is not None:
        item = {"merchant": merchant, "description": description, "amount": amount, "direction": direction}
        g = parse_sampled(_text_of(sampled), [item]).get(merchant.strip().lower())
        if g is not None:
            name, confidence = resolve_category_name(g.category) or g.category, g.confidence
    if name and confidence >= NEEDS_REVIEW_BELOW:
        return None
    names = [c.name for c in st.repo.list_categories()]
    hint = f" My best guess is {name}." if name else ""
    return Elicit(f"Where should {merchant} ({st.currency} {amount:g} on {date}) be filed?{hint}", _pick_model(names))


def _confirm_delete(ctx: Context, transaction_id: int, confirmed: bool) -> Elicit[Confirm] | None:
    if confirmed or not _client_can(ctx, "elicitation"):
        return None
    st = _tenant(ctx)
    tx = st.repo.get_transaction(transaction_id)
    if tx is None:
        return None
    return Elicit(f"Delete {tx.merchant} {st.currency} {tx.amount:g} on {tx.date}? This cannot be undone.", Confirm)


def _one_sample(ctx: Context, transaction_id: int, force: bool) -> Sample | None:
    if not _client_can(ctx, "sampling"):
        return None
    st = _tenant(ctx)
    tx = st.repo.get_transaction(transaction_id)
    if tx is None or (tx.category_id and tx.category_source == "user" and not force):
        return None
    if _rule_guess(st, tx.merchant, tx.description, tx.direction).category:
        return None
    return _sample_for(st, [_item(tx)])


def _unknown_items(st: TenantState, ids: list[int]) -> list[dict[str, Any]]:
    """Distinct merchants among `ids` that memory and rules cannot place: the only ones worth a model call."""
    seen: dict[str, dict[str, Any]] = {}
    for tx_id in ids:
        tx = st.repo.get_transaction(tx_id)
        if tx is not None and not _rule_guess(st, tx.merchant, tx.description, tx.direction).category:
            seen.setdefault(tx.merchant.strip().lower(), _item(tx))
    return list(seen.values())


def _batch_sample(ctx: Context, limit: int) -> Sample | None:
    """categorize_uncategorized: one sampling round trip covers every merchant the rules cannot place."""
    if not _client_can(ctx, "sampling"):
        return None
    st = _tenant(ctx)
    items = _unknown_items(st, st.repo.uncategorized_ids(limit))
    return _sample_for(st, items) if items else None


def _client_roots(ctx: Context) -> ListRoots | None:
    return ListRoots() if _client_can(ctx, "roots") else None


def _check_roots(roots: mt.ListRootsResult | None, file_path: str) -> None:
    """If the client declares roots, files outside them are off limits."""
    allowed = [Path(unquote(urlparse(str(r.uri)).path)).resolve() for r in (roots.roots if roots else [])]
    if not allowed:
        return
    target = Path(file_path).expanduser().resolve()
    if not any(target == root or root in target.parents for root in allowed):
        raise ValueError(f"{file_path} is outside the client's roots ({', '.join(str(a) for a in allowed)})")


def _pick_model(names: list[str]) -> type[BaseModel]:
    options = tuple([*names, SKIP])
    return create_model("PickCategory", category=(Literal[options], Field(default=SKIP, description="Where to file this transaction")))  # type: ignore[valid-type]


def _tx(tx: Transaction) -> dict[str, Any]:
    return tx.model_dump()


def _parse_iso(value: str, field: str = "date") -> str:
    try:
        return _date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date like 2026-09-17, got {value!r}") from exc


def _months_back(n: int = 12) -> list[str]:
    today = _date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _tool_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn ValueError (bad input, not found, rejected SQL) into ToolError so the client sees the message."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


# ---------------------------------------------------------------------- the server


def create_server(settings: Settings | None = None, *, db: Database | None = None, user_id: str | None = None,
                  client: str | None = None, currency: str | None = None) -> MCPServer:
    """Build the server. Bind `user_id` (and a `client` label) for in-process and stdio use; leave both unset for the
    multi-account HTTP endpoint, where the bearer-token middleware attaches the principal to each request."""
    settings = settings or load_settings()
    state = ServerState(settings, db=db, user_id=user_id, client=client, currency=currency)

    server = MCPServer(
        name="finmcp",
        title="FinMCP",
        description="Personal finance ledger: transactions, categories, budgets, goals, recurring bills, natural-language queries.",
        instructions=INSTRUCTIONS,
        version=__version__,
        subscriptions=RoutedBus(state.user_for),
    )
    server.finmcp = state  # type: ignore[attr-defined]  # used by the CLI, tests and the API

    def tenant(ctx: Context | None) -> TenantState:
        return state.tenant(ctx)

    # ------------------------------------------------------------------ tools: overview

    @server.tool(name="get_overview", annotations=READ)
    @_tool_errors
    def get_overview_tool(ctx: Context) -> dict[str, Any]:
        """The home screen in one call: spent this month and pace versus last month, safe-to-spend per day, top categories,
        budget alerts, upcoming bills, goals, recent transactions and short insights."""
        st = tenant(ctx)
        return get_overview(st.repo, currency=st.currency)

    # ------------------------------------------------------------------ tools: ledger

    @server.tool(annotations=WRITE)
    @_tool_errors
    async def add_transaction(
        ctx: Context,
        date: Annotated[str, Field(description="ISO date, YYYY-MM-DD")],
        amount: Annotated[float, Field(gt=0, description="Positive amount in the ledger currency")],
        merchant: Annotated[str, Field(min_length=1, description="Merchant or counterparty, e.g. 'Swiggy', 'Rent - Mr Sharma'")],
        direction: Annotated[Literal["debit", "credit"], Field(description="'debit' = money out (default), 'credit' = money in")] = "debit",
        description: Annotated[str | None, Field(description="Note or bank narration")] = None,
        category: Annotated[str | None, Field(description="Category to file under. Omit to auto-categorize.")] = None,
        raw_text: Annotated[str | None, Field(description="Original text (SMS, receipt line) if any")] = None,
        source: Annotated[str, Field(description="manual | receipt | statement | sms | api")] = "manual",
        auto_categorize: Annotated[bool, Field(description="Guess a category when none is given")] = True,
        ask_if_unsure: Annotated[bool, Field(description="If the guess is low-confidence and the client supports elicitation, ask the person")] = True,
        sampled: Annotated[mt.CreateMessageResult | None, Resolve(_add_sample)] = None,
        answer: Annotated[ElicitationResult[Any], Resolve(_add_question)] = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Record a transaction. Auto-categorizes unless a category is given, in which case the merchant is remembered.
        Uses the client's model through sampling when offered, and asks through elicitation when unsure."""
        st = tenant(ctx)
        iso = _parse_iso(date)
        categorizer = st.categorizer_with(sampled, [{"merchant": merchant, "description": description, "amount": amount, "direction": direction}])
        chosen: str | None = category
        asked: str | None = None
        if answer is not None and not (isinstance(answer, AcceptedElicitation) and answer.data is None):
            asked = answer.action
            if isinstance(answer, AcceptedElicitation) and answer.data.category != SKIP:
                chosen = str(answer.data.category)

        def work() -> tuple[Transaction, dict[str, Any] | None]:
            tx = st.repo.insert_transaction(date=iso, amount=amount, merchant=merchant, direction=direction, description=description,
                                            raw_text=raw_text, source=source, currency=st.currency)
            assert tx is not None
            st.repo.audit("mcp:add_transaction", "insert", "transaction", tx.id, {"merchant": merchant, "amount": amount, "direction": direction})
            categorization: dict[str, Any] | None = None
            if chosen:
                categorization = categorizer.apply_user_category(tx.id, chosen)
            elif auto_categorize:
                categorization = categorizer.categorize(tx.id)
            return tx, categorization

        tx, categorization = await anyio.to_thread.run_sync(work)
        fresh = await anyio.to_thread.run_sync(st.repo.get_transaction, tx.id)
        assert fresh is not None
        if categorization:
            await ctx.info(f"{merchant} {st.currency} {amount:g} filed under {fresh.category or 'nothing yet'} "
                           f"({categorization.get('source') or 'user'}, confidence {categorization.get('confidence') or 0:.2f})")
        return {"transaction": _tx(fresh), "categorization": categorization, "asked": asked}

    @server.tool(annotations=READ)
    @_tool_errors
    async def parse_entry(
        ctx: Context,
        text: Annotated[str, Field(min_length=1, max_length=300, description="The line as it was typed, e.g. '890 from company'")],
        merchant: Annotated[str | None, Field(description="The merchant the caller already read out of the line, if it found one")] = None,
    ) -> dict[str, Any]:
        """Read a typed line: is it money in or money out, and who was it?

        For the direction, which is the part a keyword list gets wrong. Answers from what this account has recorded
        at that merchant before, and asks the model only when its own history has no opinion. `direction` comes back
        null when neither knew, and the caller should keep its own reading."""
        st = tenant(ctx)
        guess = await anyio.to_thread.run_sync(lambda: read_entry_line(st.repo, st.provider, text, merchant))
        if guess.direction:
            await ctx.debug(f"{text!r} reads as {guess.direction} ({guess.source}, confidence {guess.confidence:.2f})")
        return guess.as_dict()

    @server.tool(annotations=WRITE)
    @_tool_errors
    def update_transaction(
        ctx: Context,
        transaction_id: int,
        date: Annotated[str | None, Field(description="ISO date")] = None,
        amount: Annotated[float | None, Field(gt=0)] = None,
        merchant: str | None = None,
        description: str | None = None,
        direction: Literal["debit", "credit"] | None = None,
        category: Annotated[str | None, Field(description="New category. Learned for this merchant. Use 'uncategorized' to clear.")] = None,
        needs_review: Annotated[bool | None, Field(description="Mark or clear the review flag")] = None,
    ) -> dict[str, Any]:
        """Edit a transaction. Setting `category` records user feedback that improves future categorization."""
        st = tenant(ctx)
        fields: dict[str, Any] = {}
        if date is not None:
            fields["date"] = _parse_iso(date)
        if amount is not None:
            fields["amount"] = float(amount)
        if merchant is not None:
            fields["merchant"] = merchant.strip()
        if description is not None:
            fields["description"] = description
        if direction is not None:
            fields["direction"] = direction
        if needs_review is not None:
            fields["needs_review"] = needs_review
        tx = st.repo.update_transaction(transaction_id, **fields) if fields else st.repo.get_transaction(transaction_id)
        if tx is None:
            raise ValueError(f"Transaction {transaction_id} not found")
        feedback = None
        if category is not None:
            if category.strip().lower() in {"", "none", "uncategorized", "null"}:
                tx = st.repo.update_transaction(transaction_id, category_id=None, category_confidence=None, category_source=None, needs_review=True)
            else:
                feedback = st.categorizer.apply_user_category(transaction_id, category)
                tx = st.repo.get_transaction(transaction_id)
        st.repo.audit("mcp:update_transaction", "update", "transaction", transaction_id, {**fields, "category": category})
        assert tx is not None
        return {"transaction": _tx(tx), "feedback": feedback}

    @server.tool(annotations=DESTRUCTIVE)
    @_tool_errors
    async def delete_transaction(
        ctx: Context,
        transaction_id: int,
        confirmed: Annotated[bool, Field(description="Skip the confirmation question (the caller already asked the person)")] = False,
        answer: Annotated[ElicitationResult[Confirm], Resolve(_confirm_delete)] = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Delete a transaction permanently. Asks the person for confirmation through elicitation unless confirmed=true."""
        st = tenant(ctx)
        before = st.repo.get_transaction(transaction_id)
        if before is None:
            raise ValueError(f"Transaction {transaction_id} not found")
        asked = answer is not None and not (isinstance(answer, AcceptedElicitation) and answer.data is None)
        if asked and not (isinstance(answer, AcceptedElicitation) and answer.data.confirm):
            return {"deleted": False, "transaction_id": transaction_id, "reason": f"not confirmed ({answer.action})"}
        if not st.repo.delete_transaction(transaction_id):
            raise ValueError(f"Transaction {transaction_id} not found")
        st.repo.audit("mcp:delete_transaction", "delete", "transaction", transaction_id, {"merchant": before.merchant, "amount": before.amount})
        await ctx.info(f"Deleted {before.merchant} {st.currency} {before.amount:g} ({before.date})")
        return {"deleted": True, "transaction_id": transaction_id}

    @server.tool(annotations=READ)
    @_tool_errors
    def list_transactions(
        ctx: Context,
        period: Annotated[str | None, Field(description="e.g. 'this month', 'last 30 days', '2026-08'. Overridden by start/end.")] = None,
        start_date: Annotated[str | None, Field(description="ISO date, inclusive")] = None,
        end_date: Annotated[str | None, Field(description="ISO date, inclusive")] = None,
        category: Annotated[str | None, Field(description="Exact category name")] = None,
        merchant: Annotated[str | None, Field(description="Substring match on merchant")] = None,
        direction: Literal["debit", "credit"] | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        search: Annotated[str | None, Field(description="Substring match on merchant, description or raw text")] = None,
        uncategorized_only: bool = False,
        needs_review_only: bool = False,
        order: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc",
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """List transactions with filters. Returns the page plus the total match count."""
        st = tenant(ctx)
        start = _parse_iso(start_date, "start_date") if start_date else None
        end = _parse_iso(end_date, "end_date") if end_date else None
        label = None
        if period and not (start or end):
            p = resolve_period(period)
            start, end, label = p.start.isoformat(), p.end.isoformat(), p.label
        cat_name = resolve_category_name(category) or category if category else None
        rows, total = st.repo.list_transactions(
            start=start, end=end, category=cat_name, merchant=merchant, direction=direction, min_amount=min_amount,
            max_amount=max_amount, search=search, uncategorized_only=uncategorized_only, needs_review_only=needs_review_only,
            order=order, limit=limit, offset=offset,
        )
        return {"count": len(rows), "total": total, "offset": offset, "period": label, "start": start, "end": end,
                "transactions": [_tx(t) for t in rows]}

    @server.tool(annotations=READ)
    @_tool_errors
    def list_categories(ctx: Context) -> dict[str, Any]:
        """Category taxonomy with kinds and monthly budget limits."""
        return {"categories": [c.model_dump() for c in tenant(ctx).repo.list_categories()]}

    @server.tool(annotations=WRITE)
    @_tool_errors
    def replace_budgets(
        ctx: Context,
        budgets: Annotated[list[BudgetLine], Field(description="The complete set of budgets to keep; every other category is cleared")],
    ) -> dict[str, Any]:
        """Make these the only budgets there are: set each one, and clear the limit on every other category.

        The default taxonomy ships with example limits so a fresh ledger is not empty, but an example is not a plan
        — left in place they quietly become the numbers the dashboard judges you against. This is what first-run
        setup calls, so what you see afterwards is only ever what you actually said."""
        st = tenant(ctx)
        wanted = {resolve_category_name(b.category) or b.category: b.monthly_limit for b in budgets}
        kept, cleared = [], []
        for cat in st.repo.list_categories():
            if cat.name in wanted:
                st.repo.set_budget(cat.name, wanted[cat.name])
                kept.append(cat.name)
            elif cat.budget_limit is not None:
                st.repo.set_budget(cat.name, None)
                cleared.append(cat.name)
        st.repo.audit("mcp:replace_budgets", "update", "category", None, {"kept": kept, "cleared": len(cleared)})
        return {"kept": kept, "cleared": cleared}

    @server.tool(annotations=WRITE)
    @_tool_errors
    def set_budget(
        ctx: Context,
        category: Annotated[str, Field(description="Category name")],
        monthly_limit: Annotated[float | None, Field(ge=0, description="Monthly limit; null removes the budget")],
    ) -> dict[str, Any]:
        """Set or clear the monthly budget for a category."""
        st = tenant(ctx)
        name = resolve_category_name(category) or category
        cat = st.repo.set_budget(name, monthly_limit)
        st.repo.audit("mcp:set_budget", "update", "category", cat.id, {"category": cat.name, "budget_limit": monthly_limit})
        return {"category": cat.model_dump()}

    # ------------------------------------------------------------------ tools: categorization

    @server.tool(annotations=WRITE)
    @_tool_errors
    async def categorize_transaction(
        ctx: Context,
        transaction_id: int,
        force: Annotated[bool, Field(description="Re-categorize even if the user set the category")] = False,
        sampled: Annotated[mt.CreateMessageResult | None, Resolve(_one_sample)] = None,
    ) -> dict[str, Any]:
        """Assign a category using merchant memory, keyword rules and a language model (the client's, through sampling,
        when offered). Returns a confidence score."""
        st = tenant(ctx)
        tx = await anyio.to_thread.run_sync(st.repo.get_transaction, transaction_id)
        categorizer = st.categorizer_with(sampled, [_item(tx)] if tx else [])
        result = await anyio.to_thread.run_sync(categorizer.categorize, transaction_id, force)
        await ctx.info(f"{result['merchant']}: {result['category'] or 'uncategorized'} via {result['source'] or 'nothing'} ({categorizer.provider.name})")
        return result

    @server.tool(annotations=WRITE)
    @_tool_errors
    async def categorize_uncategorized(
        ctx: Context,
        limit: Annotated[int, Field(ge=1, le=200, description="How many uncategorized transactions to process")] = 25,
        sampled: Annotated[mt.CreateMessageResult | None, Resolve(_batch_sample)] = None,
    ) -> dict[str, Any]:
        """Categorize up to `limit` uncategorized transactions (newest first), reporting progress, and say what changed."""
        st = tenant(ctx)
        ids = await anyio.to_thread.run_sync(st.repo.uncategorized_ids, limit)
        items = await anyio.to_thread.run_sync(_unknown_items, st, ids) if sampled is not None else []
        categorizer = st.categorizer_with(sampled, items)

        def work() -> list[dict[str, Any]]:
            results = []
            for i, tx_id in enumerate(ids, 1):
                r = categorizer.categorize(tx_id)
                results.append(r)
                anyio.from_thread.run(ctx.report_progress, float(i), float(len(ids)), f"{r['merchant']} -> {r['category'] or 'uncategorized'}")
            return results

        results = await anyio.to_thread.run_sync(work)
        categorized = [r for r in results if r["category"]]
        await ctx.info(f"Categorized {len(categorized)} of {len(results)} with {categorizer.provider.name}")
        return {"processed": len(results), "categorized": len(categorized), "still_uncategorized": len(results) - len(categorized),
                "provider": categorizer.provider.name, "results": results}

    @server.tool(name="review_queue", annotations=READ)
    @_tool_errors
    def review_queue_tool(ctx: Context, limit: Annotated[int, Field(ge=1, le=200)] = 25) -> dict[str, Any]:
        """Transactions that need a human decision: uncategorized or low-confidence, newest first, with the categorizer's best guess and reasoning."""
        st = tenant(ctx)
        rows, total = st.repo.list_transactions(needs_review_only=True, limit=limit)
        items = []
        for tx in rows:
            g = st.categorizer.guess(tx)
            items.append({**_tx(tx), "suggestion": g.category, "suggestion_confidence": round(g.confidence, 3), "suggestion_source": g.source, "reasoning": g.reasoning})
        return {"total": total, "count": len(items), "items": items,
                "how_to_resolve": "Call update_transaction(transaction_id, category=...) for each; the merchant is remembered for next time."}

    # ------------------------------------------------------------------ tools: queries and summaries

    @server.tool(annotations=READ)
    @_tool_errors
    def query_transactions(
        ctx: Context,
        question: Annotated[str, Field(min_length=3, description="Natural-language question, e.g. 'top 5 merchants last month'")],
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
    ) -> dict[str, Any]:
        """Answer a natural-language question by generating and running a read-only SQL query. Returns the SQL, its interpretation and the rows."""
        return tenant(ctx).queries.answer(question, limit)

    @server.tool(annotations=READ)
    @_tool_errors
    def run_sql(
        ctx: Context,
        sql: Annotated[str, Field(min_length=6, description="A single PostgreSQL SELECT over v_transactions / categories / monthly_summary")],
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
    ) -> dict[str, Any]:
        """Run a read-only SQL SELECT inside a read-only transaction scoped to this account. Writes and multiple statements are rejected."""
        cols, rows, truncated = tenant(ctx).repo.select(sql, limit=limit)
        return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}

    @server.tool(name="get_summary", annotations=READ)
    @_tool_errors
    def get_summary_tool(
        ctx: Context,
        period: Annotated[str, Field(description="'this month' (default), 'last month', 'last 30 days', '2026-08', 'ytd', 'YYYY-MM-DD..YYYY-MM-DD'")] = "this month",
        group_by: Literal["category", "merchant", "day", "week", "month"] = "category",
        top: Annotated[int, Field(ge=1, le=100)] = 15,
    ) -> dict[str, Any]:
        """Spending summary for a period: totals, a breakdown by category/merchant/time, income, and budget usage."""
        return get_summary(tenant(ctx).repo, period, group_by, top)

    @server.tool(name="get_budget_summary", annotations=READ)
    @_tool_errors
    def get_budget_summary_tool(
        ctx: Context,
        month: Annotated[str | None, Field(description="'YYYY-MM' or 'last month'. Default: current month.")] = None,
    ) -> dict[str, Any]:
        """Budget vs actual per category for a month, with month-end projection and status (on_track / warning / exceeded)."""
        return get_budget_summary(tenant(ctx).repo, month)

    @server.tool(name="check_budget_alerts", annotations=READ)
    @_tool_errors
    def check_budget_alerts_tool(
        ctx: Context,
        month: Annotated[str | None, Field(description="'YYYY-MM' or 'last month'. Default: current month.")] = None,
        warn_at_pct: Annotated[float, Field(ge=1, le=100, description="Warn when a category passes this share of its budget")] = 80.0,
    ) -> dict[str, Any]:
        """Proactive budget check: categories that are exceeded, past the warning threshold, or on pace to exceed their limit by month end."""
        return check_budget_alerts(tenant(ctx).repo, month, warn_at_pct)

    @server.tool(name="list_recurring", annotations=READ)
    @_tool_errors
    def list_recurring_tool(ctx: Context) -> dict[str, Any]:
        """Subscriptions, bills, rent and SIPs detected from payment rhythm: cadence, typical amount, next due date, monthly cost."""
        return list_recurring(tenant(ctx).repo)

    # ------------------------------------------------------------------ tools: goals

    @server.tool(annotations=READ)
    @_tool_errors
    def list_goals(ctx: Context) -> dict[str, Any]:
        """Savings goals with progress and the monthly amount needed to hit each deadline."""
        goals = []
        today = _date.today()
        for g in tenant(ctx).repo.list_goals():
            remaining = max(0.0, g.target - g.saved)
            months_left = None
            if g.due:
                due = _date.fromisoformat(g.due)
                months_left = max(1, (due.year - today.year) * 12 + (due.month - today.month) + (1 if due.day >= today.day else 0))
            goals.append({**g.model_dump(), "remaining": round(remaining, 2), "progress_pct": round(min(100.0, g.saved / g.target * 100), 1),
                          "monthly_needed": round(remaining / months_left, 2) if months_left else None, "months_left": months_left})
        return {"count": len(goals), "goals": goals}

    @server.tool(annotations=WRITE)
    @_tool_errors
    def upsert_goal(
        ctx: Context,
        name: Annotated[str, Field(min_length=1, max_length=80, description="Goal name, e.g. 'Emergency fund'")],
        target: Annotated[float, Field(gt=0, description="Target amount")],
        goal_id: Annotated[int | None, Field(description="Existing goal to update; omit to create")] = None,
        saved: Annotated[float | None, Field(ge=0, description="Amount saved so far (sets the balance)")] = None,
        due: Annotated[str | None, Field(description="Deadline, ISO date")] = None,
        icon: Annotated[str | None, Field(max_length=8, description="An emoji for the goal")] = None,
    ) -> dict[str, Any]:
        """Create a savings goal, or update one by goal_id."""
        st = tenant(ctx)
        due_iso = _parse_iso(due, "due") if due else None
        if goal_id is None:
            goal = st.repo.create_goal(name, target, saved=saved or 0.0, due=due_iso, icon=icon)
            st.repo.audit("mcp:upsert_goal", "insert", "goal", goal.id, {"name": name, "target": target})
        else:
            fields: dict[str, Any] = {"name": name.strip(), "target": float(target)}
            if saved is not None:
                fields["saved"] = float(saved)
            if due is not None:
                fields["due"] = due_iso
            if icon is not None:
                fields["icon"] = icon
            goal = st.repo.update_goal(goal_id, **fields)
            st.repo.audit("mcp:upsert_goal", "update", "goal", goal.id, fields)
        return {"goal": goal.model_dump()}

    @server.tool(annotations=WRITE)
    @_tool_errors
    def add_to_goal(
        ctx: Context,
        goal_id: int,
        amount: Annotated[float, Field(description="Amount to add (negative to withdraw)")],
    ) -> dict[str, Any]:
        """Move money into (or out of) a savings goal."""
        st = tenant(ctx)
        goal = st.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal {goal_id} not found")
        updated = st.repo.update_goal(goal_id, saved=max(0.0, goal.saved + float(amount)))
        st.repo.audit("mcp:add_to_goal", "update", "goal", goal_id, {"amount": amount, "saved": updated.saved})
        return {"goal": updated.model_dump(), "reached": updated.saved >= updated.target}

    @server.tool(annotations=DESTRUCTIVE)
    @_tool_errors
    def delete_goal(ctx: Context, goal_id: int) -> dict[str, Any]:
        """Delete a savings goal."""
        st = tenant(ctx)
        if not st.repo.delete_goal(goal_id):
            raise ValueError(f"Goal {goal_id} not found")
        st.repo.audit("mcp:delete_goal", "delete", "goal", goal_id)
        return {"deleted": True, "goal_id": goal_id}

    # ------------------------------------------------------------------ tools: EMIs

    @server.tool(annotations=READ)
    @_tool_errors
    def list_emis(ctx: Context) -> dict[str, Any]:
        """Loans repaid in monthly instalments (EMIs): instalments paid and left, amount still owed, next due date, end date,
        and the total monthly EMI outgo."""
        return emi_report(tenant(ctx).repo)

    @server.tool(annotations=WRITE)
    @_tool_errors
    def upsert_emi(
        ctx: Context,
        name: Annotated[str, Field(min_length=1, max_length=80, description="What the loan is for, e.g. 'iPhone 16' or 'Car loan'")],
        amount: Annotated[float, Field(gt=0, description="Monthly instalment")],
        start_date: Annotated[str, Field(description="Date of the first instalment, ISO date")],
        tenure_months: Annotated[int, Field(ge=1, le=480, description="Number of monthly instalments")],
        lender: Annotated[str | None, Field(max_length=80, description="Bank or lender, e.g. 'Bajaj Finserv'")] = None,
        principal: Annotated[float | None, Field(gt=0, description="Amount borrowed, to show the interest paid")] = None,
        emi_id: Annotated[int | None, Field(description="Existing EMI to update; omit to create")] = None,
    ) -> dict[str, Any]:
        """Add an EMI (a loan repaid in monthly instalments), or update one by emi_id."""
        st = tenant(ctx)
        start = _parse_iso(start_date, "start_date")
        if emi_id is None:
            emi = st.repo.create_emi(name, amount, start, tenure_months, lender=lender, principal=principal)
            st.repo.audit("mcp:upsert_emi", "insert", "emi", emi.id, {"name": name, "amount": amount, "tenure_months": tenure_months})
        else:
            fields: dict[str, Any] = {"name": name.strip(), "amount": float(amount), "start_date": start, "tenure_months": int(tenure_months),
                                      "lender": (lender or "").strip() or None, "principal": principal}
            emi = st.repo.update_emi(emi_id, **fields)
            st.repo.audit("mcp:upsert_emi", "update", "emi", emi.id, fields)
        return {"emi": emi_status(emi, _date.today())}

    @server.tool(annotations=DESTRUCTIVE)
    @_tool_errors
    def delete_emi(ctx: Context, emi_id: int) -> dict[str, Any]:
        """Delete an EMI (the payments already in the ledger stay)."""
        st = tenant(ctx)
        if not st.repo.delete_emi(emi_id):
            raise ValueError(f"EMI {emi_id} not found")
        st.repo.audit("mcp:delete_emi", "delete", "emi", emi_id)
        return {"deleted": True, "emi_id": emi_id}

    # ------------------------------------------------------------------ tools: activity

    @server.tool(name="recent_activity", annotations=READ)
    @_tool_errors
    def recent_activity_tool(ctx: Context, limit: Annotated[int, Field(ge=1, le=200)] = 30, offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
        """What changed recently and which client did it (web app, assistant, Claude Desktop, ...). The MCP audit trail."""
        st = tenant(ctx)
        return {"items": st.repo.recent_audit(limit, offset), "clients": st.repo.clients_seen()}

    # ------------------------------------------------------------------ tools: ingestion

    @server.tool(annotations=READ)
    @_tool_errors
    async def parse_statement(
        ctx: Context,
        file_path: Annotated[str, Field(description="Path to a bank statement PDF/CSV, a receipt image, or a text file of SMS alerts")],
        kind: Annotated[Literal["auto", "receipt", "statement", "csv", "sms"], Field(description="auto detects from the extension")] = "auto",
        roots: Annotated[mt.ListRootsResult | None, Resolve(_client_roots)] = None,
    ) -> dict[str, Any]:
        """Parse a file without importing it: returns the extracted transactions, which ones already exist, and parser warnings.
        The file must be inside one of the client's roots when the client declares any."""
        st = tenant(ctx)
        _check_roots(roots, file_path)
        await ctx.report_progress(0, 2, "parsing")
        result = await anyio.to_thread.run_sync(st.importer.parse_file, file_path, kind)
        await ctx.report_progress(1, 2, f"checking {len(result.transactions)} rows against the ledger")
        preview = await anyio.to_thread.run_sync(st.importer.preview, result)
        await ctx.report_progress(2, 2, "done")
        return preview

    @server.tool(annotations=WRITE)
    @_tool_errors
    async def import_statement(
        ctx: Context,
        file_path: Annotated[str, Field(description="Path to a bank statement PDF/CSV, a receipt image, or a text file of SMS alerts")],
        kind: Annotated[Literal["auto", "receipt", "statement", "csv", "sms"], Field(description="auto detects from the extension")] = "auto",
        dry_run: Annotated[bool, Field(description="Preview only; insert nothing")] = False,
        auto_categorize: bool = True,
        roots: Annotated[mt.ListRootsResult | None, Resolve(_client_roots)] = None,
    ) -> dict[str, Any]:
        """Parse a file, skip transactions already in the ledger (by fingerprint), insert the rest and auto-categorize them."""
        st = tenant(ctx)
        _check_roots(roots, file_path)
        importer = st.importer
        await ctx.report_progress(0, 2, "parsing")
        parsed = await anyio.to_thread.run_sync(importer.parse_file, file_path, kind)
        await ctx.report_progress(1, 2, f"importing {len(parsed.transactions)} rows")
        result = await anyio.to_thread.run_sync(functools.partial(importer.commit, parsed, auto_categorize=auto_categorize, dry_run=dry_run))
        await ctx.report_progress(2, 2, "done")
        await ctx.info(f"Import {'preview' if dry_run else 'done'}: {result.get('inserted', 0)} new, {result.get('duplicates', 0)} already there")
        return result

    @server.tool(annotations=WRITE)
    @_tool_errors
    async def import_text(
        ctx: Context,
        text: Annotated[str, Field(min_length=10, description="Pasted SMS alerts (one per line or blank-line separated) or CSV text")],
        kind: Literal["sms", "csv"] = "sms",
        source_name: Annotated[str | None, Field(description="Label for the import log")] = None,
        dry_run: Annotated[bool, Field(description="Preview only; insert nothing")] = False,
        auto_categorize: bool = True,
    ) -> dict[str, Any]:
        """Import transactions from pasted text (bank/UPI SMS alerts or CSV rows) with dedupe and auto-categorization."""
        st = tenant(ctx)
        importer = st.importer
        await ctx.report_progress(0, 2, "parsing")
        parsed = await anyio.to_thread.run_sync(importer.parse_text, text, kind, source_name)
        await ctx.report_progress(1, 2, f"importing {len(parsed.transactions)} rows")
        result = await anyio.to_thread.run_sync(functools.partial(importer.commit, parsed, auto_categorize=auto_categorize, dry_run=dry_run))
        await ctx.report_progress(2, 2, "done")
        await ctx.info(f"Import {'preview' if dry_run else 'done'}: {result.get('inserted', 0)} new, {result.get('duplicates', 0)} already there")
        return result

    # ------------------------------------------------------------------ resources

    @server.resource("finmcp://overview", name="overview", title="Overview", mime_type="application/json",
                     description="This month at a glance: spend, pace, safe-to-spend, alerts, upcoming bills, goals. Subscribe to it to learn about any write.")
    def overview_resource() -> str:
        st = tenant(None)
        return json.dumps(get_overview(st.repo, currency=st.currency), indent=2, default=str)

    @server.resource("finmcp://categories", name="categories", title="Category taxonomy", mime_type="application/json",
                     description="All categories with kind and monthly budget limit")
    def categories_resource() -> str:
        return json.dumps([c.model_dump() for c in tenant(None).repo.list_categories()], indent=2)

    @server.resource("finmcp://transactions/recent", name="recent_transactions", title="Recent transactions",
                     mime_type="application/json", description="The 50 most recent transactions")
    def recent_transactions_resource() -> str:
        rows, total = tenant(None).repo.list_transactions(limit=50)
        return json.dumps({"total": total, "transactions": [_tx(t) for t in rows]}, indent=2)

    @server.resource("finmcp://transactions/{month}", name="transactions_by_month", title="Transactions for a month",
                     mime_type="application/json", description="All transactions in a month given as YYYY-MM")
    def month_transactions_resource(month: str, ctx: Context) -> str:
        p = resolve_period(month)
        rows, total = tenant(ctx).repo.list_transactions(start=p.start.isoformat(), end=p.end.isoformat(), limit=500)
        return json.dumps({"month": month, "total": total, "transactions": [_tx(t) for t in rows]}, indent=2)

    @server.resource("finmcp://summary/monthly", name="monthly_summary", title="Monthly summary",
                     mime_type="application/json", description="Spend and income per category for the last six months")
    def monthly_summary_resource() -> str:
        return json.dumps(tenant(None).repo.monthly_by_category(6), indent=2)

    @server.resource("finmcp://recurring", name="recurring", title="Recurring payments", mime_type="application/json",
                     description="Detected subscriptions and bills with next due dates")
    def recurring_resource() -> str:
        return json.dumps(list_recurring(tenant(None).repo), indent=2)

    @server.resource("finmcp://goals", name="goals", title="Savings goals", mime_type="application/json", description="Savings goals with progress")
    def goals_resource() -> str:
        return json.dumps([g.model_dump() for g in tenant(None).repo.list_goals()], indent=2)

    @server.resource("finmcp://review-queue", name="review_queue", title="Review queue", mime_type="application/json",
                     description="Uncategorized and low-confidence transactions awaiting a human decision")
    def review_queue_resource() -> str:
        rows, total = tenant(None).repo.list_transactions(needs_review_only=True, limit=100)
        return json.dumps({"total": total, "items": [_tx(t) for t in rows]}, indent=2)

    @server.resource("finmcp://alerts", name="budget_alerts", title="Budget alerts", mime_type="application/json",
                     description="Current-month budget alerts: exceeded, warning, and on-pace-to-exceed categories")
    def alerts_resource() -> str:
        return json.dumps(check_budget_alerts(tenant(None).repo), indent=2)

    @server.resource("finmcp://activity", name="activity", title="Activity", mime_type="application/json",
                     description="The last 50 changes and which client made them")
    def activity_resource() -> str:
        st = tenant(None)
        return json.dumps({"items": st.repo.recent_audit(50), "clients": st.repo.clients_seen()}, indent=2, default=str)

    @server.resource("finmcp://imports/recent", name="recent_imports", title="Recent imports", mime_type="application/json",
                     description="The last 20 file/text imports with counts")
    def recent_imports_resource() -> str:
        return json.dumps(tenant(None).repo.recent_imports(20), indent=2, default=str)

    @server.resource("finmcp://schema", name="schema", title="Database schema", mime_type="text/markdown",
                     description="Tables, views and conventions for writing SQL against the ledger")
    def schema_resource() -> str:
        return schema_doc(tenant(None).currency)

    @server.resource("finmcp://status", name="status", title="Server status", mime_type="application/json",
                     description="Counts, date range, LLM provider and database location")
    def status_resource() -> str:
        st = tenant(None)
        first, last = st.repo.date_bounds()
        _, uncategorized = st.repo.list_transactions(uncategorized_only=True, limit=1)
        _, review = st.repo.list_transactions(needs_review_only=True, limit=1)
        return json.dumps({
            "version": __version__, "currency": st.currency, "client": st.client, "account": st.user_id,
            "database": "supabase" if settings.supabase_configured else "local", "rls": state.db.rls,
            "transactions": st.repo.count_transactions(), "categories": len(st.repo.list_categories()),
            "uncategorized": uncategorized, "needs_review": review, "first_date": first, "last_date": last,
            "llm_provider": st.provider.name, "model": st.settings.model if st.provider.is_llm else None,
            "merchant_memory": st.repo.merchant_memory_size(), "goals": len(st.repo.list_goals()),
        }, indent=2)

    # ------------------------------------------------------------------ prompts

    @server.prompt(name="monthly_spending_review", title="Monthly spending review",
                   description="Walk through a month's spending, budgets and notable changes")
    def monthly_spending_review(month: str = "") -> str:
        target = month.strip() or "this month"
        cur = settings.currency
        return (
            f"Review my spending for {target}.\n\n"
            f"1. Call get_summary(period=\"{target}\", group_by=\"category\") and get_budget_summary for the same month.\n"
            f"2. Call get_summary(period=\"{target}\", group_by=\"merchant\", top=10) for the biggest merchants.\n"
            "3. Compare against the previous month with get_summary(period=\"last month\") (or the month before the target).\n"
            "4. If anything is uncategorized, mention how many and offer to categorize.\n\n"
            f"Then write, in {cur}: the headline numbers (spent, received, net), the three most notable changes versus the "
            "previous month, every budget that is exceeded or above 80%, and two concrete, specific suggestions. "
            "Keep it under 250 words and do not invent numbers that the tools did not return."
        )

    @server.prompt(name="subscription_audit", title="Subscription audit", description="Find recurring charges and decide which ones to keep")
    def subscription_audit_prompt() -> str:
        return (
            "Audit my recurring payments. Call list_recurring, then for each subscription or bill show the merchant, cadence, "
            "typical amount and monthly cost. Flag anything that looks duplicated (two streaming services, two cloud storage plans), "
            "anything whose amount crept up (compare last_amount with amount), and anything I have not used recently if the "
            "transactions suggest so. Finish with the total monthly cost and a ranked list of what to cancel first, with the "
            "yearly saving for each. Do not cancel anything yourself; there is no tool for that."
        )

    @server.prompt(name="categorize_uncategorized", title="Categorize uncategorized transactions",
                   description="Review the uncategorized queue and file each transaction")
    def categorize_uncategorized_prompt(limit: str = "20") -> str:
        return (
            f"List up to {limit} uncategorized transactions with list_transactions(uncategorized_only=true, limit={limit}). "
            "For each one, decide the best category from list_categories using the merchant and narration, then apply it with "
            "update_transaction(transaction_id, category=...). When a merchant is genuinely ambiguous, ask me instead of guessing. "
            "Finish with a short table of what you filed and why."
        )

    @server.prompt(name="budget_planning", title="Budget planning", description="Propose monthly budgets from the last three months of actual spending")
    def budget_planning_prompt() -> str:
        return (
            "Help me set realistic monthly budgets. Call get_summary(period=\"last 3 months\", group_by=\"category\") and "
            "get_budget_summary for the current month. For each expense category, propose a limit that is about 10% below "
            "the three-month average unless spending is already lean, explain the reasoning in one line, and then offer to "
            "apply the changes with set_budget. Do not change anything until I confirm."
        )

    # ------------------------------------------------------------------ completion

    @server.completion()
    async def complete(ref: Any, argument: Any, context: Any) -> mt.Completion | None:
        """Argument completion for prompts and the month resource template."""
        name, value = argument.name, (argument.value or "")
        if name == "month":
            values = [m for m in _months_back(12) if m.startswith(value)] or ["this month", "last month"]
            return mt.Completion(values=values[:20], total=len(values), has_more=False)
        if name == "limit":
            return mt.Completion(values=[v for v in ("10", "20", "50", "100") if v.startswith(value)], has_more=False)
        return None

    return server


def seed_account(server: MCPServer, *, only_if_empty: bool = True) -> dict[str, int] | None:
    """Seed demo data for the server's bound account (CLI, tests, 'start with sample data')."""
    st: TenantState = server.finmcp.tenant()  # type: ignore[attr-defined]
    if only_if_empty and st.repo.count_transactions() > 0:
        return None
    result = seed_demo_data(st.repo)
    log.info("Seeded demo data for %s: %s", st.user_id, result)
    return result


__all__ = ["INSTRUCTIONS", "SKIP", "ServerState", "TenantState", "create_server", "current_principal", "seed_account"]
