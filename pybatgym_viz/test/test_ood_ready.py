"""Current Passenger pages and redirects, without obsolete results templates."""
import importlib
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PREFIX='/pun/dev/pybatgym_viz'


def app():
    return importlib.import_module('app').app


def test_passenger_entrypoint_exposes_wsgi_application():
    assert callable(importlib.import_module('passenger_wsgi').application)


def test_links_respect_script_name_prefix():
    response=app().test_client().get('/playground/',environ_overrides={'SCRIPT_NAME':PREFIX})
    urls=re.findall(r'(?:href|src|action)="([^"]+)"',response.get_data(as_text=True))
    assert urls and all(url.startswith(PREFIX+'/') for url in urls)


def test_templates_have_no_hardcoded_absolute_urls():
    for template in (ROOT/'views/playground').glob('*.html'):
        value=template.read_text(encoding='utf-8')
        assert 'href="/' not in value and 'src="/' not in value


def test_manifest_has_required_keys():
    value=(ROOT/'manifest.yml').read_text()
    for key in ('name','description','icon','category'):
        assert re.search(r'^'+key+r':\s*\S+',value,re.M)


def test_passenger_layout_files_exist():
    for relative in ('passenger_wsgi.py','manifest.yml','app.py','playground.py','dashboard_data.py'):
        assert (ROOT/relative).is_file()
    assert {p.name for p in (ROOT/'views').iterdir() if p.is_file()}==set()


def test_old_bookmarks_redirect_and_obsolete_navigation_is_absent():
    client=app().test_client()
    for path in ('/','/episodes','/comparison'):
        response=client.get(path,environ_overrides={'SCRIPT_NAME':PREFIX})
        assert response.status_code==302 and response.location==PREFIX+'/playground/'
    html=client.get('/playground/').get_data(as_text=True)
    assert 'Kết quả benchmark cũ' not in html and 'TensorBoard comparison' not in html
    assert 'random-seed-field' in html
