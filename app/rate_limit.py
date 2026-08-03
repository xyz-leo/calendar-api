from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# A single shared instance, imported by both app/main.py (to register the
# middleware/exception handler) and app/auth.py (to decorate the two auth
# routes with a stricter limit) — kept in its own module, not main.py, so
# neither import direction creates a circular import between them.
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
