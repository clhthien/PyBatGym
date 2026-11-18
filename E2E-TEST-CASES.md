# Stage 4 — Test case end-to-end cho hệ thống local

Phạm vi đã thống nhất: **local**, không gửi job lên Slurm và không truy cập HPC Portal.

Luồng được kiểm chứng:

```text
Chrome headless → form dưới OOD prefix → POST Launch/CSRF/idempotency
 → launcher nền → runner → Mock hoặc BatSim container thật
 → kiểm chứng dữ liệu → trạng thái/log → bảng kết quả → tải CSV
```

## Môi trường và điều kiện bắt đầu

- Docker Desktop đã hoạt động và có image PyBatGym cùng `oarteam/batsim:3.1.0` đã kiểm chứng.
- Có Python >=3.10 trên Windows để tạo `.venv-e2e`; lần kiểm chứng dùng Python 3.12.7.
- Có Google Chrome. Test dùng headless với profile riêng, không kết nối profile Chrome đang dùng.
- Service riêng `pybatgym-playground-e2e-1`, cổng 127.0.0.1:5051, output `runs/e2e/`.
- Workspace bình thường ở 5050 / `runs/playground/` được giữ riêng.
- Test preflight bắt buộc health trả `e2e_workspace=true`, `execution_mode=local`. Nếu trỏ nhầm workspace thường, bộ test từ chối chạy.
- Không mock runner, Docker hay BatSim trong suite này. Backend Mock là simulator Mock thật của PyBatGym, không phải kết quả kiểm thử giả lập.

## Bảng test case

| ID | Kịch bản / thao tác | Kết quả cần đạt |
|---|---|---|
| TC01 | Mở form bằng trình duyệt; kiểm tra link, static, form action dưới `/pun/dev/pybatgym_playground/` | Trang hoạt động, Launch khả dụng, URL đúng prefix, không có lỗi JS |
| TC02 | Chọn Mock, FCFS/SJF, seed 23 → Launch | Đi qua QUEUED/RUNNING/VERIFYING/SUCCEEDED; đủ 100 job mỗi policy, PASS, input seed được áp dụng, bảng số liệu đúng |
| TC03 | Chọn BatSim, FCFS/SJF → Launch → xem log → tải comparison CSV | Đủ 100 job/policy; 200 dòng job, native exports riêng từng episode; container exit 0; timestamp khớp <0.001 s; CSV tải khớp file thật |
| TC04 | Bỏ chọn mọi policy rồi Launch | Hiện lỗi input, không tạo run/worker |
| TC05 | Chọn workload 32 core cùng platform 4 core | Hiện cảnh báo, Launch bị khóa; chọn lại platform 32 core thì mở khóa |
| TC06 | Gửi lại cùng POST có CSRF/launch token hợp lệ | Hai response trỏ cùng run ID, chỉ một run được tạo và chạy |
| TC07 | Launch Real với timeout 1 giây | TIMED_OUT/TIMEOUT hiện trên UI, không có PASS; tài nguyên thuộc run không còn chạy |
| TC08 | Khi Real đang RUNNING, Launch thêm một run Real | Run thứ hai FAILED/REAL_BUSY; run đầu vẫn thành công, output không bị trộn |
| TC09 | Launch → đóng tab → mở lại URL run → refresh | Run tiếp tục chạy độc lập, kết quả còn truy xuất được và xuất hiện trong lịch sử |
| TC10 | Chạy lại cùng cấu hình/seed hai lần | Hai ID và thư mục khác nhau; dữ liệu lần đầu không bị ghi đè |
| TC11 | POST không CSRF; thử tải metadata/runtime/đường dẫn thoát | Request không hợp lệ bị chặn; file ngoài allowlist không được truy cập |
| TC12 | Mở form ở viewport 390×844 | Không tràn ngang toàn trang; form và Launch vẫn sử dụng được |
| TC13 | Truy vấn run ID không tồn tại hoặc sai định dạng | 404, không lộ dữ liệu |
| TC14 | Bỏ qua client validation, POST workload `../secret` | Server từ chối 400 và không tạo run |
| TC15 | Launch → ngắt mạng riêng browser context → nối lại | Hiện cảnh báo polling, runner tiếp tục; UI tự cập nhật lại tới SUCCEEDED khi có kết nối |

Kiểm tra filesystem trong suite chỉ đọc output thuộc `runs/e2e/` để đối chiếu native CSV/container state và xác nhận không ghi đè. Không sửa/xóa dữ liệu người dùng.

## Chạy tự động

PowerShell tại thư mục dự án:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
& .\scripts\test_e2e.ps1
```

Script tự tạo/tái sử dụng `.venv-e2e`, cài dependency test, khởi động riêng service E2E và chạy 15 test. Không khởi động lại Docker Desktop hoặc các service khác; không build/push/pull image. Nếu thiếu image/runtime, cần sửa môi trường trước.

Sau lần đầu có thể bỏ bước cài dependency:

```powershell
& .\scripts\test_e2e.ps1 -SkipInstall
```

Khi service E2E đã hoạt động:

```powershell
& .\scripts\test_e2e.ps1 -SkipInstall -SkipServiceStart
```

Mặc định dùng Chrome đã cài, không tải browser mới. Cache, temporary profile và môi trường test đặt trên ổ chứa repo, không yêu cầu chuyển Docker storage hoặc dọn container khác. Nếu dùng `-BrowserChannel chromium`, phải tự chuẩn bị browser Playwright trong `.e2e-cache/browsers` trước; không dùng channel này khi chưa cài browser.

Không đổi execution policy toàn hệ thống chỉ để chạy script. Nếu PowerShell chặn script theo chính sách của máy, dùng terminal/thiết lập được phép theo quản trị môi trường.

## Đọc báo cáo

Mỗi lần chạy có thư mục mới `test-results/e2e-<thời gian>/`:

```text
console.log
requirements-resolved.txt
junit.xml
report.json
test_tcXX_.../
  page.png
  trace.zip
  case.json
  <run_id>-status.json
  comparison.csv       # case download
```

- `report.json`: pass/fail, thời lượng và lỗi của từng test.
- `junit.xml`: tích hợp CI hoặc trình đọc JUnit.
- `page.png`: ảnh trạng thái cuối của test.
- `trace.zip`: lịch sử thao tác, DOM và network để debug local.
- Run thí nghiệm thật vẫn lưu đủ artifact trong `runs/e2e/<id>`.

Mở trace bằng CLI local:

```powershell
& .\.venv-e2e\Scripts\python.exe -m playwright show-trace .\test-results\TEN_SUITE\TEN_TEST\trace.zip
```

Không cần upload trace lên dịch vụ bên ngoài. Trace có thể chứa form token và log thí nghiệm, nên giữ theo chính sách dữ liệu của bạn.

## Kết quả nghiệm thu đã chạy

Ngày 14/11/2026: 14 test đầu đạt trong 140.26 giây; TC15 kiểm tra bổ sung đạt trong 9.11 giây. Tổng **15/15 E2E** đạt. Bộ unit/integration regression **65/65** đạt trong 40.51 giây. Các lượt được lưu riêng để không ghi đè bằng chứng.

Đây là nghiệm thu một cấu hình local đã nêu, không phải chứng minh mọi workload hoặc mọi hệ điều hành đều đúng. NGINX/Passenger OOD thật, Slurm, Podman/HPC và training PPO không nằm trong suite local này.

## Phạm vi bảo toàn

- Chỉ service mới `playground-e2e` và container episode mang nhãn runner của các run test được tạo/quản lý.
- Không xóa image, volume hoặc container cũ; không prune/reset Docker.
- Service 5050, shell, viz, tensorboard và dữ liệu `runs/playground` được giữ nguyên.
- Suite chạy tuần tự, không dùng pytest-xdist; các tình huống đồng thời được tạo có kiểm soát trong TC08.
- Container test đã kết thúc được giữ lại để kiểm tra theo chính sách runner hiện tại. Test chạy lại sẽ tạo thêm run/container nên cần lên kế hoạch retention riêng khi dùng CI lâu dài.

## Nguồn kỹ thuật

- https://playwright.dev/python/docs/intro
- https://playwright.dev/python/docs/browsers
- https://playwright.dev/python/docs/trace-viewer
