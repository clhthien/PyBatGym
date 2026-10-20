# """Kiểm tra mức độ sẵn sàng cho Open OnDemand (không cần cluster OOD).

# Mỗi test tương ứng một yêu cầu của mô hình Passenger app trong tutorial OSC:
# - có entry point passenger_wsgi.py cung cấp biến `application`
# - link không bị hỏng khi app chạy dưới đường dẫn con (OOD: /pun/dev/<tên app>/)
# - template không chứa đường dẫn tuyệt đối viết cứng
# - manifest.yml có đủ khóa để hiện trên Dashboard
# - app không sập khi chưa có dữ liệu
# """
# import os
# import re
# import sys
# import tempfile
# from pathlib import Path

# ROOT = Path(__file__).resolve().parent.parent
# sys.path.insert(0, str(ROOT))
# PREFIX = "/pun/dev/pybatgym_viz"


# def _flask_app():
#     empty = tempfile.mkdtemp()
#     os.environ["PYBATGYM_RESULTS_DIR"] = empty
#     os.environ["PYBATGYM_LOGS_DIR"] = empty
#     import importlib
#     import app
#     importlib.reload(app)
#     return app.app


# def test_passenger_entrypoint_exposes_wsgi_application():
#     _flask_app()
#     import importlib
#     import passenger_wsgi
#     importlib.reload(passenger_wsgi)
#     assert callable(passenger_wsgi.application)


# def test_links_respect_script_name_prefix():
#     client = _flask_app().test_client()
#     for path in ("/", "/episodes", "/comparison"):
#         html = client.get(path, environ_overrides={"SCRIPT_NAME": PREFIX}).get_data(as_text=True)
#         hrefs = re.findall(r'href="([^"]+)"', html)
#         assert hrefs, "không tìm thấy link nào trong " + path
#         assert all(h.startswith(PREFIX) for h in hrefs), (path, hrefs)


# def test_templates_have_no_hardcoded_absolute_urls():
#     for tpl in (ROOT / "views").glob("*.html"):
#         text = tpl.read_text(encoding="utf-8")
#         assert 'href="/' not in text and 'src="/' not in text, tpl.name


# def test_manifest_has_required_keys():
#     text = (ROOT / "manifest.yml").read_text(encoding="utf-8")
#     for key in ("name", "description", "icon", "category"):
#         assert re.search(r"^%s:\s*\S+" % key, text, re.M), "manifest.yml thiếu khóa " + key


# def test_passenger_layout_files_exist():
#     for rel in ("passenger_wsgi.py", "manifest.yml", "app.py", "command.py"):
#         assert (ROOT / rel).is_file(), rel
#     for rel in ("views", "public", "tmp"):
#         assert (ROOT / rel).is_dir(), rel


# def test_pages_do_not_crash_without_data():
#     client = _flask_app().test_client()
#     for path in ("/", "/episodes", "/comparison"):
#         assert client.get(path).status_code == 200, path
"""Kiểm tra mức độ sẵn sàng cho Open OnDemand (không cần cluster OOD).

Mỗi test tương ứng một yêu cầu của mô hình Passenger app trong tutorial OSC:
- có entry point passenger_wsgi.py cung cấp biến `application`
- link không bị hỏng khi app chạy dưới đường dẫn con (OOD: /pun/dev/<tên app>/)
- template không chứa đường dẫn tuyệt đối viết cứng
- manifest.yml có đủ khóa để hiện trên Dashboard
- app không sập khi chưa có dữ liệu
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PREFIX = "/pun/dev/pybatgym_viz"


def _flask_app():
    try:
        import flask  # noqa: F401
    except ImportError as exc:
        raise AssertionError(
            "Chưa cài Flask trong môi trường này. Chạy: pip install flask "
            "(container viz đã tự cài; container shell thì chưa)."
        ) from exc
    empty = tempfile.mkdtemp()
    os.environ["PYBATGYM_RESULTS_DIR"] = empty
    os.environ["PYBATGYM_LOGS_DIR"] = empty
    import importlib
    import app
    importlib.reload(app)
    return app.app


def test_passenger_entrypoint_exposes_wsgi_application():
    _flask_app()
    import importlib
    import passenger_wsgi
    importlib.reload(passenger_wsgi)
    assert callable(passenger_wsgi.application)


def test_links_respect_script_name_prefix():
    client = _flask_app().test_client()
    for path in ("/", "/episodes", "/comparison"):
        html = client.get(path, environ_overrides={"SCRIPT_NAME": PREFIX}).get_data(as_text=True)
        hrefs = re.findall(r'href="([^"]+)"', html)
        assert hrefs, "không tìm thấy link nào trong " + path
        assert all(h.startswith(PREFIX) for h in hrefs), (path, hrefs)


def test_templates_have_no_hardcoded_absolute_urls():
    for tpl in (ROOT / "views").glob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        assert 'href="/' not in text and 'src="/' not in text, tpl.name


def test_manifest_has_required_keys():
    text = (ROOT / "manifest.yml").read_text(encoding="utf-8")
    for key in ("name", "description", "icon", "category"):
        assert re.search(r"^%s:\s*\S+" % key, text, re.M), "manifest.yml thiếu khóa " + key


def test_passenger_layout_files_exist():
    for rel in ("passenger_wsgi.py", "manifest.yml", "app.py", "command.py"):
        assert (ROOT / rel).is_file(), rel
    for rel in ("views", "public", "tmp"):
        assert (ROOT / rel).is_dir(), rel


def test_pages_do_not_crash_without_data():
    client = _flask_app().test_client()
    for path in ("/", "/episodes", "/comparison"):
        assert client.get(path).status_code == 200, path
