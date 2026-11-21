# Training RL và TensorBoard — nâng cao

Khả năng có trong source, **không thuộc Launch benchmark đã nghiệm thu**. Không cần training để demo dashboard. Các script chưa được kiểm chứng lại trong lần dọn tài liệu này.

- `pybatgym.experiments.train_ppo_markable`: MaskablePPO + RealEval.
- `pybatgym.experiments.train_ppo_standard`: PPO + RealEval.
- `pybatgym.experiments.run_benchmark`: benchmark thấp tầng; demo nên dùng runner quản lý ID/verification/container.

## Chuẩn bị

Đọc cấu hình script: workload/platform, timestep mặc định lớn, save_path, writers, tần suất RealEval. Cần PyTorch, stable-baselines3, sb3-contrib, TensorBoard, pybatsim.

```powershell
cd F:\DACN\Code\DATN\PyBatGym
docker compose -p pybatgym -f docker-compose.yml up -d --no-deps --no-build --pull never shell
docker exec pybatgym-shell-1 /opt/venv/bin/python -c "import torch, stable_baselines3, sb3_contrib, tensorboard"
```

Khi thực sự muốn training, chọn một lệnh:

```powershell
docker exec -it pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.experiments.train_ppo_markable
docker exec -it pybatgym-shell-1 /opt/venv/bin/python -m pybatgym.experiments.train_ppo_standard
```

Luồng này dùng adapter cũ với RealEval, không tự dùng managed episode container của runner mới. Phải chuẩn bị backend BatSim trước. Nếu dùng Compose BatSim cũ, sau khi Python đã bind socket, mở terminal riêng:

```powershell
docker compose -p pybatgym -f docker-compose.yml up -d --no-deps --no-build --pull never batsim
```

Không chạy đồng thời benchmark Real của runner. Chưa có form training; chưa cam kết end-to-end khi chưa xác nhận dependency/config/backend.

## TensorBoard độc lập

```powershell
docker compose -p pybatgym -f docker-compose.yml up -d --no-deps --no-build --pull never tensorboard
Start-Process 'http://localhost:6006/'
```

Đọc logs/. Chưa có event thì chưa có dashboard. Log/model do script cấu hình, khác run artifacts. Khi xong stop riêng tensorboard, giữ log/model. Quay lại [RUNNER.md](RUNNER.md) để demo phần đã kiểm chứng.
