"""Offline release startup; never install packages at runtime."""
import os
import subprocess
import sys

subprocess.run([sys.executable, '/workspace/release/manifest.py', 'check'], check=True)
args = sys.argv[1:]
if args:
    os.execv(sys.executable, [sys.executable, *args])
os.execv(sys.executable, [sys.executable, '/workspace/pybatgym_viz/serve_local.py'])
