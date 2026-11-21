"""Scheduling Playground: launcher, dashboard, and run artifacts."""
import os
from flask import Flask, redirect, url_for
from playground import initialize

app = Flask(__name__, template_folder='views', static_folder='public')
initialize(app)

@app.get('/')
def index():
    return redirect(url_for('playground.home'))

@app.get('/episodes')
@app.get('/comparison')
def legacy_results():
    # Old bookmarks resolve to the current launcher, not a second results store.
    return redirect(url_for('playground.home'), code=302)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')
