"""Local WSGI preview with the same SCRIPT_NAME prefix used by Passenger.

This is not an Open OnDemand installation or an HPC authentication server.
"""
import os
from pathlib import Path
import sys
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
from werkzeug.middleware.dispatcher import DispatcherMiddleware

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from passenger_wsgi import application

PREFIX = '/pun/dev/pybatgym_playground'


def landing(environ, start_response):
    if environ.get('PATH_INFO') == '/':
        start_response('302 Found', [('Location', PREFIX + '/playground/'), ('Content-Length', '0')])
        return [b'']
    start_response('404 Not Found', [('Content-Type', 'text/plain; charset=utf-8')])
    return [b'Not found']


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5050'))
    preview = DispatcherMiddleware(landing, {PREFIX: application})
    print(f'PyBatGym Passenger WSGI preview: {PREFIX}/playground/', flush=True)
    make_server('0.0.0.0', port, preview, server_class=ThreadedServer).serve_forever()
