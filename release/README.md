# Local release 20261120

Image: `ghcr.io/clhthien/pybatgym:local-20261120`. Không ghi đè latest, chưa push registry.

Đây là bản chụp ngày 20/11, không tự cập nhật theo source hiện tại. Kiểm tra ngày
22/11 cho thấy tag `latest` đã đổi image ID so với base ghim ở script build;
script sẽ từ chối build để tránh dùng nhầm môi trường. Demo hiện tại dùng
development 5050 theo RUNNER.md. Không bỏ kiểm tra base để build lại một cách tùy ý.

## Cách đóng gói

- `scripts/build_release.ps1` xác nhận image nền đúng ID đã kiểm chứng rồi tạo alias local cho build; không cần quyền pull GHCR. Ghim cả digest môi trường nền và phiên bản dependency web trong `web.lock.txt`.
- `Dockerfile.release` xóa source cũ **trong layer image mới**, copy source hiện tại và 3 workload 100/1.000/10.000 job. Không copy logs, model, run dữ liệu người dùng hoặc file 100.000/1 triệu job.
- Không cài package khi startup. `release/start.py` kiểm tra hash source trước khi chạy. Manifest và pip freeze thực tế nằm trong image ở `/opt/pybatgym-release/`.
- `environment.reference.txt` là snapshot môi trường phát triển để đối chiếu, không phải lock dùng pip-install lại toàn bộ CUDA. Đây là incremental release từ base image cũ; dung lượng vẫn lớn, chưa phải image CPU tối ưu.
- Không có Docker socket thì image vẫn chạy Mock/test. Real local cần bind workspace và socket để simulator nhìn thấy cùng input/output. Không hỗ trợ Podman/Slurm chỉ bằng đổi tag image.

## Build lại (PowerShell tại repo)

```powershell
& .\scripts\build_release.ps1
```

Script cần base image cũ đúng ID. Máy khác có thể dùng image release đã chuyển/push sau này; không giả định base private luôn pull được. Build có thể cần mạng lấy wheel web; **run không cần pip/Internet**. Image nền cũ giữ nguyên.

## Bản đã xuất và chạy thử trên máy này

Source độc lập xuất từ image: `F:\DACN\Code\DATN\PyBatGym-release-20261120`.
Giao diện: **http://localhost:5052/**. Development vẫn ở 5050. Chạy lại:

```powershell
cd F:\DACN\Code\DATN\PyBatGym
$env:PYBATGYM_RELEASE_WORKSPACE='F:\DACN\Code\DATN\PyBatGym-release-20261120'
docker compose -p pybatgym -f compose.release.yml up -d --no-deps --no-build --pull never playground-release
```

Không sửa source trong thư mục release: startup sẽ từ chối nếu khác hash. Output mới nằm trong `PyBatGym-release-20261120/runs/playground/`. Muốn cập nhật source: build tag mới, xuất workspace mới, kiểm thử trước khi chuyển phiên bản. Không mount development repo vào release service.

## Xuất workspace trên máy khác

Sau khi có đúng image, tạo container không chạy rồi copy source ra **thư mục mới**:

```powershell
docker create --name pybatgym-release-export ghcr.io/clhthien/pybatgym:local-20261120
New-Item -ItemType Directory -Path F:\PyBatGym-release-20261120
docker cp pybatgym-release-export:/workspace/. F:\PyBatGym-release-20261120
```

Giữ container export nếu cần kiểm tra, không phải service chạy. Đặt biến workspace phù hợp rồi dùng Compose trên. Thư mục repo chỉ giữ Compose/build tools; code thực thi trong workspace xuất từ image. BatSim image `oarteam/batsim:3.1.0` phải có sẵn và mạng `pybatgym_default` do Compose project tạo.

## Kiểm chứng

76/76 regression PASS trong container image mới, `--network none`, không bind source host. Kiểm chứng browser Real trên workspace xuất image ghi ở `verification.local.json` sau khi hoàn tất. Không phải bằng chứng HPC, PPO training hoặc rebuild sạch từ Ubuntu. Container kiểm thử, image cũ, dữ liệu và các project Docker khác không bị xóa.
