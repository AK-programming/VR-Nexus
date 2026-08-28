"""Pydantic request/response models, one module per API area (auth, library,
tender). Kept separate from app.models, which is the SQLAlchemy layer: these
describe what crosses the wire, those describe what's in the database."""
