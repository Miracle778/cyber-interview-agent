"""R3 personal profile domain package.

Isolated domain package that reuses the existing Workspace Runtime, Session,
Execution, Event, Middleware, HITL and Knowledge Publication infrastructure.
Domain facts live in the Runtime SQLite tables (migration 016) and private
content-addressed artifacts; LangGraph checkpoints keep orchestration state only.
"""
