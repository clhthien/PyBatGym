"""Entry point cho Passenger (tương đương config.ru của app Ruby).
Passenger tìm biến `application` trong file này."""
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT.parent))
sys.path.insert(0, str(APP_ROOT))
from app import app as flask_app  # noqa: E402
from werkzeug.utils import redirect  # noqa: E402


def application(environ, start_response):
    # Launching the app always opens the scheduling playground.
    if environ.get('PATH_INFO', '/') in ('', '/'):
        destination = environ.get('SCRIPT_NAME', '').rstrip('/') + '/playground/'
        return redirect(destination)(environ, start_response)
    return flask_app(environ, start_response)
