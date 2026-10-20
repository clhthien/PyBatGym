# PyBatGym

> **PyBatGym** là môi trường huấn luyện học tăng cường tương thích **Gymnasium/OpenAI Gym** cho bài toán **lập lịch job trong hệ thống HPC**. Framework đóng vai trò cầu nối giữa các thuật toán RL như PPO/MaskablePPO và bộ mô phỏng BatSim/Event-driven simulator.

---

## Mục tiêu chính

PyBatGym được xây dựng nhằm:

1. Mô phỏng môi trường huấn luyện học tăng cường tuân thủ chuẩn Gymnasium/OpenAI Gym.
2. Kết nối BatSim với các RL framework thông qua một interface thống nhất.
3. Đo lường và đánh giá hiệu quả các chính sách lập lịch trên hệ thống tính toán hiệu năng cao.

---

## Tính năng nổi bật

- **Gymnasium-compatible Environment:** hỗ trợ `reset()`, `step()`, `action_space`, `observation_space`.
- **Event-driven Simulation:** mô phỏng theo điểm sự kiện thay vì fixed timestep.
- **Mock + Real Adapter:** hỗ trợ `EventDrivenMockAdapter` để huấn luyện nhanh và `RealBatsimAdapter` để đánh giá với BatSim.
- **Action Masking:** loại bỏ các hành động không hợp lệ, phù hợp với MaskablePPO.
- **Baseline Scheduling:** hỗ trợ so sánh với FCFS, SJF, EASY/Smallest-Fitting.
- **TensorBoard + CSV Logging:** theo dõi quá trình huấn luyện và xuất kết quả benchmark.
- **Docker-ready:** môi trường chạy đã được đóng gói sẵn bằng Docker Compose.

---

## Yêu cầu hệ thống

| Thành phần                     | Yêu cầu                                         |
| ------------------------------ | ----------------------------------------------- |
| Git                            | Dùng để clone source code                       |
| Docker Desktop / Docker Engine | Dùng để chạy môi trường đã đóng gói             |
| Docker Compose                 | Đi kèm Docker Desktop hoặc cài riêng trên Linux |
| RAM                            | Khuyến nghị từ 8GB trở lên                      |
| Trình duyệt                    | Dùng để xem TensorBoard                         |

> Nếu chỉ sử dụng Docker, bạn không cần cài thủ công Python, BatSim, PyTorch hay Stable-Baselines3 trên máy host.

---

## Cài đặt nhanh từ repository

### 1. Clone project

```bash
git clone https://github.com/clhthien/PyBatGym.git
cd PyBatGym
```

### 2. Khởi động TensorBoard

```bash
docker-compose up -d tensorboard
```

Sau đó mở trình duyệt tại:

```text
http://localhost:6006
```

Ban đầu TensorBoard có thể hiển thị chưa có dữ liệu. Sau khi chạy huấn luyện, các biểu đồ sẽ xuất hiện trong giao diện này.

### 3. Khởi động container làm việc

```bash
docker-compose up -d shell
```

### 4. Truy cập vào shell container

```bash
docker-compose exec shell bash
```

### 5. Kích hoạt môi trường Python trong container

```bash
source /opt/venv/bin/activate
```

Nếu kích hoạt thành công, terminal sẽ hiển thị tiền tố `(venv)`.

---

## Chạy huấn luyện MaskablePPO

Bên trong container, sau khi đã kích hoạt môi trường ảo:

```bash
python pybatgym/experiments/train_ppo_markable.py
```

Quá trình huấn luyện gồm hai phần chính:

1. **Training trên Mock Simulator:** sử dụng mô phỏng event-driven tốc độ cao để học chính sách lập lịch.
2. **Evaluation trên Real BatSim:** định kỳ đánh giá policy với BatSim để kiểm tra hiệu năng trên môi trường mô phỏng HPC thực tế hơn.

---

## Xem kết quả trên TensorBoard

Sau khi script training bắt đầu ghi log, mở hoặc refresh:

```text
http://localhost:6006
```

Một số nhóm biểu đồ quan trọng:

| Nhóm biểu đồ                   | Ý nghĩa                                                           |
| ------------------------------ | ----------------------------------------------------------------- |
| `train/*`                      | Theo dõi loss, entropy, learning rate và quá trình tối ưu của PPO |
| `Training/Reward`              | Reward thu được trong quá trình huấn luyện                        |
| `Evaluation/Reward`            | Reward khi đánh giá policy                                        |
| `Comparison_Real/Utilization`  | So sánh mức tận dụng tài nguyên của RL với baseline               |
| `Comparison_Real/Slowdown`     | So sánh bounded slowdown                                          |
| `Comparison_Real/Waiting_Time` | So sánh thời gian chờ trung bình                                  |

---

## Dữ liệu benchmark

Ngoài TensorBoard, PyBatGym có thể xuất dữ liệu định lượng ra CSV thông qua `BenchmarkLogger`.

Các file thường dùng:

- `benchmark_summary.csv`: tổng hợp chỉ số chính của từng policy/workload.
- `per_episode_metrics.csv`: ghi lại chỉ số chi tiết theo từng episode.

Các chỉ số đánh giá chính gồm:

- Average Waiting Time
- Bounded Slowdown
- Utilization
- Throughput
- Makespan
- Total Reward

---

## Cấu trúc repository

```text
PyBatGym/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── configs/
├── data/
│   ├── platforms/
│   └── workloads/
├── examples/
├── logs/
├── models/
├── pybatgym/
│   ├── adapters/
│   ├── baselines/
│   ├── callbacks/
│   ├── config/
│   ├── core/
│   ├── envs/
│   ├── experiments/
│   ├── plugins/
│   ├── results/
│   ├── rewards/
│   └── spaces/
├── pybatgym_viz/
│   ├── public/
│   ├── test/
│   ├── tmp/
│   ├── view/
├── scripts/
└── tests/
```

### Các module chính

| Module                  | Vai trò                                               |
| ----------------------- | ----------------------------------------------------- |
| `pybatgym/envs/`        | Chứa `PyBatGymEnv`, môi trường Gymnasium chính        |
| `pybatgym/adapters/`    | Adapter giao tiếp với Mock Simulator hoặc BatSim      |
| `pybatgym/spaces/`      | Xây dựng observation và ánh xạ action                 |
| `pybatgym/rewards/`     | Tính toán reward đa mục tiêu                          |
| `pybatgym/baselines/`   | Các thuật toán heuristic baseline                     |
| `pybatgym/callbacks/`   | Callback đánh giá và ghi log trong quá trình training |
| `pybatgym/experiments/` | Script huấn luyện và đánh giá PPO/MaskablePPO         |
| `pybatgym/plugins/`     | Logger, benchmark logger và công cụ hỗ trợ            |
| `configs/`              | File cấu hình thí nghiệm                              |
| `data/`                 | Workload và platform cho mô phỏng                     |

---

## Lệnh thường dùng

### Mở shell container

```bash
docker-compose up -d shell
docker-compose exec shell bash
source /opt/venv/bin/activate
```

### Chạy TensorBoard

```bash
docker-compose up -d tensorboard
```

Truy cập:

```text
http://localhost:6006
```

### Chạy training chính

```bash
python pybatgym/experiments/train_ppo_markable.py
```

### Khởi động BatSim Docker

Khi cần chạy đánh giá với **Real BatSim**, mở thêm một terminal khác trên máy host và chạy:

```bash
docker-compose up batsim
```

Nếu muốn chạy BatSim ở chế độ nền:

```bash
docker-compose up -d batsim
```

> Thứ tự khuyến nghị: chạy script Python trong `shell` trước, sau đó mới chạy `docker-compose up batsim` để BatSim kết nối vào socket `tcp://shell:28000`.

### Tắt toàn bộ container

```bash
docker-compose down
```

### Xóa log cũ trên Windows PowerShell

```powershell
Remove-Item -Path "logs\*" -Recurse -Force
```

---

## Troubleshooting

### `docker-compose` không chạy

Kiểm tra Docker Desktop đã được bật. Nếu dùng Docker Compose v2, có thể thay `docker-compose` bằng:

```bash
docker compose
```

Ví dụ:

```bash
docker compose up -d shell
```

### Không vào được shell container

Đảm bảo container đã chạy:

```bash
docker-compose up -d shell
```

Sau đó vào container:

```bash
docker-compose exec shell bash
```

### Lỗi thiếu package Python

Kích hoạt lại môi trường ảo:

```bash
source /opt/venv/bin/activate
```

Nếu vẫn lỗi, cài lại project trong container:

```bash
pip install -e /workspace
```

### TensorBoard báo `No dashboards are active`

Nguyên nhân thường là chưa có log training. Hãy chạy script training trước:

```bash
python pybatgym/experiments/train_ppo_markable.py
```

Sau đó refresh lại `http://localhost:6006`.

### Port 6006 bị chiếm

Tắt container đang chạy:

```bash
docker-compose down
```

Sau đó chạy lại TensorBoard:

```bash
docker-compose up -d tensorboard
```

---

## License

MIT
