"""Train PPO Agent on Custom Workload Trace.

This script demonstrates training a Reinforcement Learning agent (PPO)
on the `tiny_workload.json` trace we extracted earlier, and prints 
the performance metrics compared to classic heuristics.
"""

import os
from pathlib import Path

from stable_baselines3 import PPO

from pybatgym.config.base_config import PyBatGymConfig
from pybatgym.envs import PyBatGymEnv
from pybatgym.plugins.tensorboard_logger import TensorBoardLoggerPlugin
from pybatgym.plugins.logger import CSVLoggerPlugin
from pybatgym.baselines import run_baseline, sjf_policy, easy_backfilling_policy, fcfs_policy


def main():
    print("======================================================")
    print("   PyBatGym: Training PPO on Custom Workload Trace    ")
    print("======================================================")

    data_dir = Path(__file__).parent.parent / "data"
    trace_path = data_dir / "workloads" / "tiny_workload.json"
    
    # 1. Configure the Environment
    config = PyBatGymConfig()
    config.platform.total_nodes = 5
    config.platform.cores_per_node = 1
    config.workload.source = "trace"
    config.workload.trace_path = str(trace_path)
    
    # Enable Hybrid reward for smooth learning
    config.reward_weights.utilization = 0.4
    config.reward_weights.waiting_time = 0.4
    config.reward_weights.slowdown = 0.2
    
    # Add plugins (TensorBoard + CSV)
    config.plugins = [
        TensorBoardLoggerPlugin(log_dir="logs/tensorboard_ppo"),
        CSVLoggerPlugin(output_dir="logs/csv_logs")
    ]
    
    # 2. Create the Env
    env = PyBatGymEnv(config=config)
    
    print("\n[1/3] Running Heuristic Baselines for Comparison...")
    # SJF Baseline
    sjf_metrics = run_baseline(env, sjf_policy, num_episodes=1)
    # EASY Backfilling Baseline
    easy_metrics = run_baseline(env, easy_backfilling_policy, num_episodes=1)
    
    print("\n[2/3] Training PPO Agent (10,000 steps)...")
    # Using small batch size because episodes are very short (6 jobs)
    model = PPO("MultiInputPolicy", env, verbose=0, n_steps=64, batch_size=32, ent_coef=0.01)
    model.learn(total_timesteps=10000)
    
    print("\n[3/3] Evaluating Trained PPO Agent...")
    obs, info = env.reset(seed=42)
    done = False
    ep_reward = 0.0
    
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(int(action))
        ep_reward += reward
        done = terminated or truncated
        
    # Calculate PPO metrics manually from completed jobs
    ppo_metrics = {"avg_waiting_time": 0.0, "avg_slowdown": 0.0, "avg_utilization": 0.0}
    completed = env._adapter.get_completed_jobs()
    if completed:
        makespan = env._adapter.get_current_time()
        total_cores = env.unwrapped._state.get("resource").total_cores
        
        ppo_metrics["avg_waiting_time"] = sum(j.waiting_time for j in completed) / len(completed)
        ppo_metrics["avg_slowdown"] = sum(j.bounded_slowdown for j in completed) / len(completed)
        if makespan > 0 and total_cores > 0:
            busy_time = sum(j.actual_runtime * j.requested_resources for j in completed)
            ppo_metrics["avg_utilization"] = busy_time / (makespan * total_cores)

    print("\n======================================================")
    print("                 FINAL COMPARISON                     ")
    print("======================================================")
    print(f"{'Metric':<25} | {'SJF Baseline':<15} | {'EASY Backfill':<15} | {'Trained PPO':<15}")
    print("-" * 75)
    
    def format_val(val):
        return f"{val:.2f}"
        
    metrics_to_print = [
        ("Avg Waiting Time (s_sim)", "avg_waiting_time", "avg_waiting_time"),
        ("Avg Slowdown", "avg_slowdown", "avg_slowdown"),
        ("Avg Utilization (%)", "avg_utilization", "avg_utilization"),
    ]
    
    for label, base_key, ppo_key in metrics_to_print:
        sjf_v = sjf_metrics.get(base_key, 0.0)
        easy_v = easy_metrics.get(base_key, 0.0)
        ppo_v = ppo_metrics.get(ppo_key, 0.0)
        
        # Format utilization specifically
        if "Utilization" in label:
            sjf_str = f"{sjf_v*100:.1f}%"
            easy_str = f"{easy_v*100:.1f}%"
            ppo_str = f"{ppo_v*100:.1f}%"
        else:
            sjf_str = format_val(sjf_v)
            easy_str = format_val(easy_v)
            ppo_str = format_val(ppo_v)
            
        print(f"{label:<25} | {sjf_str:<15} | {easy_str:<15} | {ppo_str:<15}")

    print("\nTraining complete! You can view the learning curves by running:")
    print("  tensorboard --logdir logs/tensorboard_ppo")
    
    env.close()


if __name__ == "__main__":
    main()
