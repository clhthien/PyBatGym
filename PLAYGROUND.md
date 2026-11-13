# Stage 3 — Scheduling Playground (ứng dụng Passenger cho OOD)

## Mở bản local

Mở **http://localhost:5050/**. Trang tự chuyển sang đường dẫn mô phỏng OOD `/pun/dev/pybatgym_playground/playground/`.

Service `pybatgym-playground-1` đã được tạo riêng, không thay thế viz ở cổng 5000. Nếu cần khởi động lại riêng service này:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml up -d --no-deps --no-build playground
```

Chỉ khi bạn muốn dừng giao diện mới, dùng:

```powershell
docker compose -p pybatgym -f docker-compose.yml -f compose.playground.yml stop playground
```

Không dừng container playground trong lúc có run đang chạy bên trong nó. Không dùng `down` cho toàn bộ project khi chỉ muốn dừng UI.

## Sử dụng

1. Chọn `gen_c32_s0`, preset `medium_batsim` (32 core mô phỏng).
2. Chọn Mock để kiểm tra nhanh, hoặc BatSim để chạy simulator thật.
3. Chọn FCFS/SJF, seed và thời gian chạy tối đa.
4. Bấm **Launch experiment**. Request trả về trang run ngay; thí nghiệm chạy ở tiến trình nền.
5. Theo dõi trạng thái và log; trang tự cập nhật khoảng 2 giây/lần.
6. Khi **Thành công / PASS**, xem bảng so sánh và bấm **Tải CSV**.
7. Về trang đầu để tìm lại run. Refresh/đóng tab không tự hủy thí nghiệm. Mỗi run có ID, config và output riêng.

Platform core là tài nguyên mô phỏng; chưa phải số CPU được Slurm cấp. Bản này chạy benchmark, chưa có training RL hoặc form tài nguyên Slurm.

Output local nằm ở `F:\DACN\Code\DATN\PyBatGym\runs\playground\<run_id>` như Stage 2; có thêm submission.json/submission.meta.json/launcher.log cho Launch nền.

## Các thành phần

- `pybatgym_viz/playground.py`: blueprint Flask cho form, danh sách, chi tiết, status polling và download.
- `views/playground/`: template riêng; `public/playground.css/js`: giao diện và polling, không phụ thuộc CDN.
- `pybatgym.runner.submit.submit()`: validate và cấp run ID, khởi chạy launcher tách khỏi request HTTP.
- `pybatgym.runner.launch`: đọc submission của run, gọi service Stage 2 vào đúng thư mục đã tạo.
- `service.allocate()` / `Status(..., resume=True)`: giữ lịch sử CREATED/QUEUED khi nối vào runner.
- `passenger_wsgi.py`: WSGI entrypoint; root Passenger chuyển đến playground, giữ SCRIPT_NAME prefix.
- `manifest.yml`, `bin/python`: metadata và wrapper Python cho OOD.
- `serve_local.py`: WSGI preview với prefix OOD; **không phải một bản cài OOD/Passenger/Slurm đầy đủ**.
- `compose.playground.yml`: chỉ thêm service local ở 127.0.0.1:5050, dùng image PyBatGym sẵn có và Docker socket cho runner Real.

Image gốc chưa có Flask trong layer dùng cho container mới, nên `start_local.py` cài Flask 3.1.3 từ package registry vào riêng container preview nếu thiếu. Không build/push image, không đổi môi trường các container khác. Khi recreate container có thể cần mạng để cài lại Flask; bản phát hành sau nên đóng gói dependency web vào image riêng/tag đã kiểm chứng.

## Kiểm tra đầu-cuối đã thực hiện

- Launch Mock từ trình duyệt → tự chuyển từ QUEUED đến SUCCEEDED/PASS; FCFS/SJF đủ 100/100 job.
- Launch BatSim từ trình duyệt → SUCCEEDED/PASS, đủ 100/100 job mỗi policy; native exports từng episode khớp trong sai số <0.001 giây; tải CSV bằng nút trên giao diện thành công.
- Giữ được các run Stage 2/CLI trong cùng workspace, xem lại bằng ID.
- Kiểm thử input sai, CSRF, chống gửi trùng, đọc log giới hạn 64 KiB, chặn path traversal/symlink khi tải file.
- Kiểm thử WSGI root, đường dẫn SCRIPT_NAME, form action, static URL, polling và download dưới prefix `/pun/dev/...`.
- 64 test riêng biệt đạt: 62 test runner/benchmark/baseline/viz và 2 test Passenger root/per-user defaults bổ sung.

Lệnh chạy bộ kiểm thử:

```powershell
docker exec -e PYTHONDONTWRITEBYTECODE=1 pybatgym-shell-1 /opt/venv/bin/python -m pytest -p no:cacheprovider tests/test_playground_runner.py tests/test_run_benchmark.py tests/test_baselines.py pybatgym_viz/test -q
```

## Chuẩn bị đưa vào OOD thật

Ứng dụng giữ cấu trúc Passenger: WSGI entrypoint, manifest, public, tmp, Python wrapper. Theo tài liệu OOD, ứng dụng Python dùng `passenger_wsgi.py`; wrapper `bin/python` chọn môi trường Python. Sandbox và cài app dùng chung phụ thuộc cấu hình/quản trị viên.

Các việc cần làm trên HPCC khi được cấp Sandbox:

1. Có Python >=3.10 và environment chứa PyBatGym/Flask. Python 3.9.25 trên cụm hiện tại chưa được kiểm chứng với runner mới.
2. Đưa repository đã sửa lên home, tạo `.venv` trong repo hoặc cấu hình `PYBATGYM_PYTHON` trỏ đúng interpreter.
3. Quản trị viên bật gateway/Sandbox cho tài khoản. Chỉ tạo `~/ondemand/dev` không bảo đảm portal này nhận app.
4. Khi được phép, tạo symlink từ `~/ondemand/dev/pybatgym_playground` tới thư mục `pybatgym_viz` của repo, đặt executable cho `bin/python`, rồi mở app từ Develop.
5. Xác nhận app chạy dưới `/pun/dev/pybatgym_playground/`, static/link/poll/download đúng prefix và dữ liệu thuộc home của đúng user.
6. Nối lớp submit Slurm và runtime trên compute node ở stage tích hợp tiếp theo. Không bật chế độ local để chạy workload nặng trên node portal/login.

Mặc định app Passenger **không cho Launch** (`PYBATGYM_EXECUTION_MODE=disabled`), và dùng output per-user `~/ondemand/data/pybatgym_playground/runs`. Compose local bật `local` một cách tường minh và chọn `/workspace/runs/playground` để truy cập native Docker output. Thư mục kết quả user cần quyền ghi riêng.

Chưa đăng nhập/triển khai app lên HPCC, chưa chạy NGINX/Passenger hoặc dashboard OOD thật trong local. Các kiểm tra prefix là WSGI simulation và test client; chưa được coi là bằng chứng nghiệm thu deploy OOD. Quyền Sandbox và lớp Slurm là phần còn lại để đạt luồng HPC đầy đủ.

## Phạm vi truy cập

Ứng dụng dành cho local loopback hoặc Passenger **per-user** được OOD xác thực; chưa có account/login/authorization đa người dùng riêng. Không publish service preview ra LAN/Internet.

- POST Launch cần CSRF token; submit lặp dùng idempotency claim nguyên tử.
- Form không nhận shell command, Docker image, network, container name hay đường dẫn tùy ý.
- Download chỉ cho một allowlist artifact của run, kiểm tra đường dẫn và symlink; không mở runtime metadata/session key qua download.
- Mỗi OS user có store riêng trên OOD; không dùng thư mục source system app làm nơi ghi chung.
- Real chạy tuần tự trong một runtime. CLI shell và service UI là hai runtime riêng, nhưng mỗi run dùng container/endpoint/output riêng.
- Timeout, trạng thái lỗi và kiểm chứng kết quả tiếp tục do runner Stage 2 quản lý.
- Chưa có nút cancel trên UI hoặc cơ chế phục hồi sau mất điện/SIGKILL. Restart container UI có thể làm gián đoạn các run trong container.

## Nguồn kỹ thuật

- OOD Python Passenger application: https://osc.github.io/ood-documentation/latest/tutorials/tutorials-passenger-apps/python-starter-app.html
- OOD development mode: https://osc.github.io/ood-documentation/latest/how-tos/app-development/enabling-development-mode.html
