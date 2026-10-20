# pybatgym_viz – web app hiển thị kết quả PyBatGym (theo mẫu Passenger app của Open OnDemand)

Tham chiếu: https://osc.github.io/ood-documentation/release-1.2/app-development/tutorials-passenger-apps/ps-to-quota.html

## Đối chiếu với tutorial OSC

| Tutorial (Ruby/Sinatra) | Bản này (Python/Flask) | Vai trò |
|---|---|---|
| config.ru | passenger_wsgi.py | Entry point cho Passenger |
| app.rb | app.py | Routes + cấu hình app |
| command.rb | command.py | Chạy lệnh shell + parse output |
| test/test_command.rb | test/test_command.py | Unit test phần parse |
| views/index.html, layout.html | views/index.html, episodes.html, layout.html | Template hiển thị |
| manifest.yml | manifest.yml | Tên, icon, category trên Dashboard |
| public/, tmp/ | public/, tmp/ | Static file; `touch tmp/restart.txt` để restart Passenger |
| Gemfile | requirements.txt | Dependency |

Luồng xử lý mỗi request (đúng 3 bước của tutorial):
lấy raw data từ lệnh shell (`cat <csv>`) -> parse thành object trung gian (`Table`) -> render bảng/biểu đồ.

## Chạy thử trong Docker (Windows)

Service `viz` đã có sẵn trong `docker-compose.yml` ở thư mục gốc repo (cùng cách với service `tensorboard`). Từ thư mục gốc:

```powershell
docker-compose up -d viz
docker-compose logs -f viz
```

Mở http://localhost:5000. Biến môi trường `PYBATGYM_RESULTS_DIR`, `PYBATGYM_LOGS_DIR`, `FLASK_DEBUG` được đặt trong `docker-compose.yml`.

## Test

```bash
pip install flask pytest && pytest test/ -v
```

`test/test_command.py` kiểm tra phần đọc và parse dữ liệu. `test/test_ood_ready.py` kiểm tra mức độ sẵn sàng cho Open OnDemand (entry point `passenger_wsgi.py`, link khi chạy dưới đường dẫn con, khóa trong `manifest.yml`, không sập khi chưa có dữ liệu).
