"""One module per router. Each defines its own `router = APIRouter(prefix=...)`
and app/main.py includes them, so adding an endpoint never means touching the
application setup."""
