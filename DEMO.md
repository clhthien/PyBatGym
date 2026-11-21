# Demo GVHD — PyBatGym Scheduling Playground

Chuẩn bị ngày 22/11/2026. Lệnh khởi chạy đầy đủ ở [RUNNER.md](RUNNER.md).

Kiểm chứng lượt cuối: **86/86 regression PASS** (16,00 giây), **16/16 browser E2E
PASS** (134,93 giây). Báo cáo: `test-results/e2e-20261122-020335-814/` và bản tóm
tắt lưu trong `demo/20261122/validation.json`, `e2e-report.json`. Bài Real 1.000
chạy lại đạt SUCCEEDED/PASS. Đã sửa lỗi I/O tạm thời khi đọc log qua Windows bind
mount làm status HTTP 500; test mới kiểm tra thông báo và phục hồi log.

## 1. Mục tiêu và câu mở đầu

“Em xây dựng playground để người dùng chọn workload, policy và cấu hình, sau đó
Launch một thí nghiệm scheduling, theo dõi tiến độ và lấy kết quả có kiểm chứng.
Hôm nay em demo luồng local dùng BatSim thật. Runner đã chạy bài nhỏ trên Slurm
HPCC, còn giao diện tích hợp vào portal OOD chưa triển khai.”

Không giới thiệu đây là thuật toán RL mới hoặc hệ thống thay thế scheduler Slurm.
Slurm cấp tài nguyên thật để chạy thí nghiệm; FCFS/SJF trong PyBatGym điều phối
các job của hệ thống **mô phỏng** bên trong thí nghiệm đó.

## 2. Chuẩn bị trước buổi gặp

- Mở Docker Desktop, khởi động riêng `playground` theo RUNNER.md. Dùng cổng 5050.
- Mở sẵn [form](http://localhost:5050/), một dashboard PASS và `demo/20261122/index.html`.
- Kiểm tra health, đủ image BatSim/PyBatGym; tránh build/pull/cài package trong buổi demo.
- Chọn Real 100 job, `gen_c32_s0`, `medium_batsim`, FCFS + SJF, seed 0, timeout 120 s.
- Chuẩn bị kết quả 1.000/10.000 đã PASS, nói rõ ngày chạy và run ID. Không đợi bài
  10.000 chạy xong trong buổi gặp. Không mở cùng lúc nhiều run Real trong cùng service.
- Để sẵn status.json, verification.json, results/comparison_table.csv và jobs.csv.
- Không cần chạy bộ test trước mặt thầy. Show báo cáo test đã hoàn tất cùng ngày.

Kết quả 1.000 chạy lại hôm nay:
`20261121T190121-6f75ce0d836c` (run ID theo UTC, ngày tại Việt Nam là 22/11).
Dashboard: http://localhost:5050/pun/dev/pybatgym_playground/playground/runs/20261121T190121-6f75ce0d836c/dashboard

Kết quả 10.000 dùng lại lần 19/11:
`20261119T154030-82db4fee7e16`; không tuyên bố vừa chạy lại 10.000 hôm nay.

## 3. Kịch bản trình bày 10–15 phút

| Thời gian | Thao tác | Nội dung nói |
|---|---|---|
| 0–2 phút | Show sơ đồ luồng và form | Bài toán, đầu vào, platform, policy, seed; benchmark hiện tại chưa training RL |
| 2–3 phút | Launch Real 100 | Backend kiểm tra cấu hình, tạo run ID; runner chạy nền và lưu config |
| 3–5 phút | Mở Dashboard Live | Completed, queue/running, core allocation; hai đồng hồ thực/mô phỏng |
| 5–7 phút | SUCCEEDED/PASS, mở Chi tiết | Đủ 100 job mỗi policy, 0 invalid action, đối chiếu native BatSim, tải CSV |
| 7–10 phút | Replay, đổi FCFS/SJF | Kéo thời gian, chỉ vị trí job chờ/chạy; giải thích p95 và utilization |
| 10–12 phút | Mở biểu đồ 1.000/10.000 | So sánh cùng input, kết luận có giới hạn; đây là kết quả đã chạy trước |
| 12–15 phút | Báo cáo test + HPC | Đã đạt gì, thiếu OOD UI/RL gì; xin thầy chốt ưu tiên và hỗ trợ quyền |

Luồng local: Form → backend → runner → PyBatGym/pybatsim → BatSim riêng từng
episode → verification → status/log/CSV → Live/Replay.
Luồng HPC: Form handler/CLI → sbatch → compute node chạy cùng runner bằng
Python 3.10 và Podman → kết quả về home NFS. Handler đã thử bằng Flask test
client; chưa có trang PyBatGym được cài trong menu OOD thật.

Nếu Real đang chạy thì chỉ quan sát. Nếu thất bại, mở status/stderr và trình bày
lỗi; có thể chuyển sang run PASS đã chuẩn bị, nói rõ đó là kết quả lưu trước.
Không dùng Mock làm bằng chứng BatSim thật. Không bỏ qua verification để demo.

## 4. Sau khi chạy, em có gì để báo cáo?

Có **một thí nghiệm có thể truy vết**: cấu hình, workload/seed, run ID, metadata/hash,
log, trạng thái, CSV job/step, metrics theo episode, native BatSim output và verification.
Dashboard giúp quan sát; CSV là dữ liệu để đối chiếu và phân tích.

| Bằng chứng | Câu hỏi trả lời |
|---|---|
| status + verification + số job + invalid actions | Chạy hoàn chỉnh và đúng điều kiện kiểm chứng chưa? |
| Cột mean waiting và p95 waiting | Trung bình và nhóm job phải chờ lâu khác nhau thế nào? |
| Utilization + makespan | Tài nguyên mô phỏng dùng thế nào, toàn bài kết thúc khi nào? |
| Queue/running theo thời gian | Ùn tắc xuất hiện ở đâu, policy giải phóng hàng đợi thế nào? |
| Allocation timeline + một job trong explorer | Core nào cấp cho job nào, timestamp submit/start/finish là gì? |
| Đường CDF waiting time | Tỷ lệ job đã có thời gian chờ dưới một ngưỡng; phần đuôi có cải thiện không? |
| Báo cáo regression/E2E | Form, xử lý lỗi, run riêng, tải file và Live/Replay đã được thử ra sao? |

Biểu đồ xuất sẵn: [demo/20261122/index.html](demo/20261122/index.html).
PNG để đưa slide, PDF để đưa báo cáo; summary.csv chứa số liệu,
provenance.json chứa nguồn và SHA256. Mean/p95/makespan dùng **giây mô phỏng**.
Utilization là **32 core mô phỏng**, CPU/RAM worker là tài nguyên tiến trình thật,
không phải giám sát toàn cụm HPCC.
p95 dùng phương pháp nearest-rank, thống nhất với dashboard.

Kết quả tiêu biểu từ CSV:

| Workload | Mean wait FCFS (s) | Mean wait SJF (s) | SJF giảm mean wait |
|---|---:|---:|---:|
| 100 job | 1405,384 | 539,404 | khoảng 61,62% |
| 1.000 job | 11654,058 | 8257,151 | khoảng 29,15% |
| 10.000 job | 112527,244 | 100311,180 | khoảng 10,86% |

“Trên workload tổng hợp và seed 0 này, SJF giảm thời gian chờ trung bình so với
FCFS. Em xem thêm p95, utilization, makespan và phân bố để tránh kết luận chỉ
từ trung bình. Hiện SJF chọn trong cửa sổ top-K của môi trường; kết quả chưa chứng
minh SJF luôn tốt hơn hoặc policy RL đã học tốt.”

Đừng nói “1.000 job tốt hơn 100 job” chỉ vì số phần trăm khác; đó là các input
khác nhau. Một seed chưa có ý nghĩa thống kê; không vẽ error bar giả. Bước đánh
giá tiếp theo cần nhiều workload/trace và seed, cùng điều kiện so sánh.

## 5. Những câu thầy có thể hỏi

**Sau khi chạy em thu được gì?**
“Một bộ kết quả có cấu hình và log đi kèm, các bảng job/step/metrics, kết quả
đối chiếu native BatSim và dashboard phát lại. Em dùng mean/p95 waiting,
utilization và makespan để so sánh policy trên cùng workload.”

**Sao biết chạy đúng, không chỉ hiện giao diện?**
“Runner yêu cầu đủ job, không invalid action, kết thúc episode, simulator exit 0
và timestamp CSV khớp native BatSim dưới 0,001 giây trước khi ghi PASS.
Đó là kiểm chứng tính nhất quán thực thi; chưa chứng minh simulator khớp mọi hệ thống thực.”

**RL nằm ở đâu?**
“Source có environment và script PPO/MaskablePPO. Giao diện và runner demo hiện
benchmark baseline FCFS/SJF; chưa có luồng training RL được nghiệm thu.
Em chưa dùng kết quả baseline làm bằng chứng policy học được.”

**Đã làm plugin trên portal chưa?**
“Chưa cài UI vào OOD. Em đã chạy runner qua Slurm/Podman ở job 8158/8159, mỗi
policy 100 job, PASS; đã thử handler form/status/dashboard/download trên HPC bằng
test client. Bước còn thiếu là triển khai Passenger app/gateway và thử UI thực trên portal.”

**Đóng web có dừng job không? Có ghi đè lần trước không?**
“Run chạy nền; mở lại theo ID để xem. Mỗi lần có thư mục riêng; có test lặp chạy,
đóng/mở tab, request trùng, timeout và trường hợp Real đang bận.”

**Đây có phải Grafana không?**
“Đây là dashboard Flask/Canvas của PyBatGym có Live/Replay, không phải cài
Grafana/Prometheus và không đo trạng thái của toàn cụm.”

## 6. Phạm vi đã đạt và còn thiếu

| Nội dung | Trạng thái |
|---|---|
| Local form → Launch → Real → status/log/CSV → dashboard | Đã có, kiểm thử lại trong lượt chuẩn bị demo |
| Run riêng, kiểm tra input, lỗi rõ, timeout/Real busy | Có regression và browser E2E |
| Live/Replay, policy comparison, allocation/job explorer | Có; dữ liệu Live cần telemetry của run mới |
| Real 100/1.000/10.000 local | Có run PASS; 1.000 chạy lại hôm nay; 10.000 là bằng chứng 19/11 |
| Python 3.10.22 + Podman + Slurm trên HPC | Đã kiểm chứng bài nhỏ trên node13 |
| UI PyBatGym được cài và Launch trực tiếp trong OOD | Chưa |
| Đồng bộ toàn bộ source mới nhất từ local lên HPC | Chưa; HPC còn bản thử riêng, thiếu một số bổ sung local |
| Training/evaluate PPO từ web và so baseline | Chưa nghiệm thu |
| Nhiều seed, trace thực, phân tích thống kê | Chưa đủ |
| Theo dõi toàn cụm, production nhiều user, triển khai GHCR mới | Chưa nghiệm thu |
| Release image ngày 20/11 | Bản chụp cũ; base latest đã thay đổi, chưa rebuild theo source hiện tại |

## 7. Tiếp theo và việc cần thầy hỗ trợ

1. Chốt mốc nghiệm thu: benchmark playground trước, training RL là mốc sau hay
   bắt buộc có trong thời hạn đồ án. Gửi thầy run/ảnh/CSV và phạm vi rõ ràng này.
2. Đồng bộ source đã commit lên thư mục thử HPC; chạy lại Real nhỏ qua Slurm.
3. Nhờ thầy/quản trị cấp Develop/Sandbox/gateway hoặc hỗ trợ cài app Passenger
   theo cách portal cho phép. Xin đường dẫn triển khai, quy tắc restart và cách rollback.
4. Xác nhận partition/account/QOS, giới hạn CPU/RAM/time, cách chạy Podman được
   hỗ trợ và quản lý scratch/image trên các node. Hiện chỉ nghiệm thu Real ở node13.
5. Sau khi UI vào OOD: kiểm thử trực tiếp form → sbatch → kết quả/download qua
   trình duyệt. Hoàn thành bước này mới gọi là plugin portal chạy end-to-end.
6. Nếu thầy yêu cầu RL: thêm request training/evaluate, checkpoint, seed, policy
   đã học; đánh giá trên workload tách khỏi training, so cùng baseline và tài nguyên.
7. Xin workload/trace, metric và tiêu chí đánh giá thầy mong muốn. Làm nhiều
   workload/seed trước khi kết luận ưu thế thuật toán.

Mẫu trao đổi: “Em đã có luồng local hoàn chỉnh và runner Slurm chạy BatSim thật
bài nhỏ. Em xin thầy xem demo, chốt phạm vi training RL, và hỗ trợ đầu mối quản trị
để triển khai UI trong OOD. Em sẽ thử luồng portal thật sau khi có gateway/app root.”

## 8. Tạo lại biểu đồ

Script chỉ đọc run SUCCEEDED/PASS, không chạy simulator hoặc sửa output cũ.
Môi trường riêng `.venv-report`; không cần matplotlib trong image runtime:

```powershell
python -m venv .venv-report
.\.venv-report\Scripts\python.exe -m pip install -r demo/20261122/requirements-report.txt
.\.venv-report\Scripts\python.exe scripts/export_demo_report.py --run runs/playground/20261121T190121-6f75ce0d836c --run runs/playground/20261119T154030-82db4fee7e16 --output test-results/demo-charts-new
```

Output phải là thư mục mới, tránh ghi đè báo cáo cũ.
