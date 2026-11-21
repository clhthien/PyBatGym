# Real BatSim smoke trên HPCC — 21/11/2026

Đã thực thi qua shell portal bằng tài khoản thien.caolehoan, không sudo hoặc thay cấu hình hệ thống. Đây là smoke độc lập, chưa tích hợp runner web/Slurm adapter.

## Kết quả

| Job | Mục đích | Kết quả |
| --- | --- | --- |
| 8151 | Python 3.10.22 và dependency trên node1 | COMPLETED 0:0, PASS |
| 8153–8155 | Probe Podman trên node1/node13 | FAILED 1:0 khi pull; debug ghi SIGTERM, có cảnh báo thiếu user systemd bus. Chưa xác định riêng từng nguyên nhân |
| 8156 | Probe quyền ghi/tmpfs/export trên node13 | COMPLETED 0:0, 55 giây, PODMAN_WRITABLE_BATSIM_WAITING_PASS |
| 8157 | PyBatGym FCFS + BatSim 3.1.0, workload gen_c32_s0, 32 core mô phỏng | COMPLETED 0:0, 38 giây, verification PASS |

Job 8157: 100/100 job, 294 steps, 0 invalid actions, simulator exit 0, sai số native timestamp lớn nhất 0.00037 giây, average waiting time 1405.3840384 giây mô phỏng. Có sự kiện Simulation ENDS, CSV job/step và native CSV.

## Cách chạy đã vượt probe

- Python: /home/thien.caolehoan/venvs/pybatgym310/bin/python.
- Xin 1 CPU, 4G RAM, partition compute, account general, qos normal, node13; walltime tối đa 10 phút; episode có timeout 180 giây.
- Podman storage/runroot/XDG_RUNTIME_DIR ở thư mục /tmp riêng từng job, tránh storage trên NFS home.
- Cấu hình CONTAINERS_CONF riêng trong scratch: cgroup_manager=cgroupfs, events_logger=file; unset DBUS_SESSION_BUS_ADDRESS trong job. Không sửa cấu hình tài khoản/toàn máy.
- overlay.ignore_chown_errors=true vì chưa có subuid/subgid. Đây là workaround đã thử cho image cụ thể, không kết luận phù hợp mọi image hoặc mọi node.
- /tmp container là tmpfs mode 1777; output bind vào scratch có quyền ghi; input data bind read-only từ home. Giao tiếp localhost qua host network trong job.
- Bản sao adapter cũ + subclass smoke riêng: bỏ monkeypatch running_simulation, cập nhật clock trước event/finish_time khi completion, không phát READY trước decision barrier. Code gốc ~/PyBatGym giữ nguyên.
- Dừng đúng container pbg-real-<jobid> ở cleanup; không prune/remove container khác. Scratch và container thí nghiệm được giữ, có thể còn chiếm disk trên node.

Đã thay nhiều yếu tố giữa các probe, nên không khẳng định nguyên nhân ba lượt đầu chỉ do RAM hoặc chỉ do cgroup/systemd.

## Artifact trên HPC

Probe: ~/slurm_checks/podman-real.tsfp7tf1/

Episode: ~/slurm_checks/real-episode.w3juwyb2/

- real.sbatch, smoke.py, adapter_fixed.py
- job_8157.out, job_8157.err, batsim.log
- jobs.csv, steps.csv, container.json, verification.json
- native/batsim_jobs.csv, native/batsim_schedule.csv, schedule trace và machine states

```bash
cat ~/slurm_checks/real-episode.w3juwyb2/verification.json
sacct -j 8157 --format=JobID,State,ExitCode,Elapsed,NodeList
```

Không submit lại vào cùng CHECK_DIR vì output/native đã tồn tại. Khi tái kiểm chứng phải tạo thư mục mới, copy smoke.py/real.sbatch và truyền CHECK_DIR mới, giữ nguyên log lần trước.

## Phạm vi còn lại

Chưa kiểm chứng nhiều policy, workload lớn, các compute node khác, PPO, recovery/cancel đầy đủ hoặc deployment OOD. Chưa đưa runner mới lên cụm. Bước tiếp theo là chuẩn hóa runtime Podman/submit Slurm trong source và xác nhận nhiều episode, sau đó nối UI. Không dùng PASS này để nói nút Launch portal đã gửi job.
