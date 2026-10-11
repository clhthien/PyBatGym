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

1. Thêm service vào `docker-compose.yml` của PyBatGym:

```yaml
  viz:
    image: ghcr.io/thinhnguyen7204/pybatgym:latest
    volumes:
      - .:/workspace
    working_dir: /workspace/pybatgym_viz
    # Cùng kiểu với service tensorboard: ghi đè entrypoint (shell service dùng entrypoint.sh riêng)
    entrypoint: [ "/bin/bash", "-c", "source /opt/venv/bin/activate && pip install -q flask && python app.py" ]
    ports:
      - "5000:5000"
    environment:
      - PYTHONUNBUFFERED=1
```

2. Chép thư mục `pybatgym_viz/` vào gốc repo PyBatGym, rồi:

```powershell
docker-compose up -d viz
```

3. Mở http://localhost:5000

Thư mục kết quả mặc định: `/workspace/pybatgym/results` (đổi bằng biến `PYBATGYM_RESULTS_DIR`).

## Test

```bash
pip install pytest && pytest test/ -v
```
