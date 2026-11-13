"""Bootstrap only the dedicated local preview container, without rebuilding images."""
import importlib.util
from pathlib import Path
import runpy
import subprocess
import sys

if importlib.util.find_spec('flask') is None:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', 'flask==3.1.3'])
runpy.run_path(str(Path(__file__).with_name('serve_local.py')), run_name='__main__')
