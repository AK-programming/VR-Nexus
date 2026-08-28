"""Cross-cutting infrastructure: settings, database session, JWT/password
helpers, and the tender WebSocket connection registry. Nothing in here
imports from app.api or app.services, so it can be used by any layer
without a circular import."""
