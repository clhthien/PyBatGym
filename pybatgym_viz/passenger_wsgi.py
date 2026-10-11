"""Entry point cho Passenger (tương đương config.ru của app Ruby).
Passenger tìm biến `application` trong file này."""
from app import app as application  # noqa: F401
