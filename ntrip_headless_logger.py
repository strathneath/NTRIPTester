import socket
import base64
import time
import csv
import os
from datetime import datetime, timezone, timedelta
import matplotlib
matplotlib.use('Agg')  # Headless mode for server/CI environments
import matplotlib.pyplot as plt

# ==========================================
# CONFIGURATION
# ==========================================
NTRIP_CASTER = "caster.emlid.com"
NTRIP_PORT = 2101
MOUNTPOINT = "MP25727"
USER = "u33679"
PASSWORD = "376rfe"

LOG_FILE = "ntrip_reliability_log.csv"
GRAPH_SUMMARY_OUTPUT = "ntrip_session_summary.png"   # Option 2: Long-term Timeline
GRAPH_OVERLAY_OUTPUT = "ntrip_overlay_analysis.png"  # Option 1: 0-60s Trace Overlay
DROPOUT_THRESHOLD_SEC = 2.5
SAMPLE_DURATION_SEC = 60                   # Collect data for 60 seconds per run
LOCAL_TZ = timezone(timedelta(hours=9, minutes=30))  # Local time UTC+9:30
# ==========================================

def init_csv():
    """Ensure the CSV log exists with proper headers."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_utc", "latency_sec"])

def log_packet(timestamp_utc, latency):
    """Append a single packet arrival event to the historical CSV log."""
    with open(LOG_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp_utc.isoformat(), latency])

def generate_graphs():
    """Reads CSV data and renders both Option 1 (Overlay) and Option 2 (Timeline Summary)."""
    if not os.path.exists(LOG_FILE):
        print("No log file found yet. Skipping graph generation.")
        return

    sessions = {} # Key: Sample session start time, Value: list of (elapsed_sec, latency)

    try:
        with open(LOG_FILE, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("timestamp_utc") and row.get("latency_sec"):
                    dt_utc = datetime.fromisoformat(row["timestamp_utc"])
                    dt_local = dt_utc.astimezone(LOCAL_TZ)
                    latency = float(row["latency_sec"])

                    # Group data into 10-minute buckets based on session timestamp
                    session_key = dt_local.replace(minute=(dt_local.minute // 10) * 10, second=0, microsecond=0)
                    
                    if session_key not in sessions:
                        sessions[session_key] = []
                    
                    sessions[session_key].append((dt_local, latency))
    except Exception as e:
        print(f"Error reading log file: {e}")
        return

    if not sessions:
        print("Log file contains no data yet. Skipping graph generation.")
        return

    # ==========================================
    # GRAPH 1: OPTION 2 - TIMELINE SUMMARY
    # ==========================================
    session_times = []
    avg_latencies = []
    max_latencies = []
    has_dropout = []

    for s_time in sorted(sessions.keys()):
        records = sessions[s_time]
        lats = [r[1] for r in records]
        
        session_times.append(s_time)
        avg_latencies.append(sum(lats) / len(lats))
        max_lat = max(lats)
        max_latencies.append(max_lat)
        has_dropout.append(max_lat > DROPOUT_THRESHOLD_SEC)

    fig_summary, ax_summary = plt.subplots(figsize=(12, 6))
    ax_summary.axhline(y=1.0, color='g', linestyle='--', alpha=0.5, label='Ideal Latency (1.0s)')
    ax_summary.axhline(y=DROPOUT_THRESHOLD_SEC, color='r', linestyle='--', alpha=0.5, label='Dropout Limit (2.5s)')

    ax_summary.plot(session_times, avg_latencies, color='#1f77b4', marker='o', markersize=4, linestyle='-', linewidth=1, label='Sample Avg Latency')

    for st, avg_l, max_l, dropped in zip(session_times, avg_latencies, max_latencies, has_dropout):
        if dropped:
            ax_summary.vlines(x=st, ymin=avg_l, ymax=max_l, color='red', linewidth=2, alpha=0.8)
            ax_summary.plot(st, max_l, marker='x', color='red', markersize=6)
        else:
            ax_summary.vlines(x=st, ymin=avg_l, ymax=max_l, color='#1f77b4', linewidth=1, alpha=0.4)

    total_samples = len(sessions)
    bad_samples = sum(has_dropout)

    ax_summary.set_title(f"NTRIP Stream 10-Min Timeline Summary (UTC+9:30)\nTotal Samples: {total_samples} | Runs with Dropouts: {bad_samples}")
    ax_summary.set_xlabel("Local Time")
    ax_summary.set_ylabel("Packet Interval (Seconds)")
    ax_summary.legend(loc='upper right')
    ax_summary.grid(True, linestyle=':', alpha=0.6)
    plt.xticks(rotation=45)
    plt.tight_layout()

    plt.savefig(GRAPH_SUMMARY_OUTPUT)
    plt.close(fig_summary)
    print(f"Timeline summary graph saved to {GRAPH_SUMMARY_OUTPUT}")

    # ==========================================
    # GRAPH 2: OPTION 1 - 0-60s OVERLAY ANALYSIS
    # ==========================================
    fig_overlay, ax_overlay = plt.subplots(figsize=(12, 6))
    ax_overlay.axhline(y=1.0, color='g', linestyle='--', alpha=0.5, label='Ideal Latency (1.0s)')
    ax_overlay.axhline(y=DROPOUT_THRESHOLD_SEC, color='r', linestyle='--', alpha=0.5, label='Dropout Limit (2.5s)')

    # Plot each 60-second session overlaid on a relative 0-60 second x-axis
    for s_time in sorted(sessions.keys()):
        records = sessions[s_time]
        if not records:
            continue
            
        start_dt = records[0][0]
        relative_seconds = [(r[0] - start_dt).total_seconds() for r in records]
        latencies = [r[1] for r in records]

        # Use subtle transparency so dense overlapping lines build up visually
        ax_overlay.plot(relative_seconds, latencies, linestyle='-', linewidth=1, alpha=0.35)

    ax_overlay.set_title(f"NTRIP 60-Second Overlay Analysis ({total_samples} Combined Runs)\nEvaluates Packet Consistency Over the 60s Sample Window")
    ax_overlay.set_xlabel("Elapsed Time Within Sample Window (Seconds)")
    ax_overlay.set_ylabel("Packet Interval (Seconds)")
    ax_overlay.legend(loc='upper right')
    ax_overlay.grid(True, linestyle=':', alpha=0.6)
    plt.tight_layout()

    plt.savefig(GRAPH_OVERLAY_OUTPUT)
    plt.close(fig_overlay)
    print(f"Overlay analysis graph saved to {GRAPH_OVERLAY_OUTPUT}")

def run_sample_session():
    init_csv()
    
    auth_str = f"{USER}:{PASSWORD}"
    auth_encoded = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    request = (
        f"GET /{MOUNTPOINT} HTTP/1.1\r\n"
        f"User-Agent: NTRIP PythonClient/1.0\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n"
    )
    if USER or PASSWORD:
        request += f"Authorization: Basic {auth_encoded}\r\n"
    request += "\r\n"

    print(f"Connecting to {NTRIP_CASTER}:{NTRIP_PORT} for 60-second sampling session...")
    session_start = time.time()
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((NTRIP_CASTER, NTRIP_PORT))
        s.sendall(request.encode('utf-8'))
        
        response = s.recv(1024).decode('utf-8', errors='ignore')
        if "200 OK" not in response and "ICY" not in response:
            print(f"Connection Failed. Server responded with:\n{response}")
            s.close()
            generate_graphs()
            return

        print("Connected! Sampling packet delivery...")
        s.settimeout(5)
        last_packet_time = time.time()

        while time.time() - session_start < SAMPLE_DURATION_SEC:
            try:
                data = s.recv(4096)
                if not data:
                    print("Stream disconnected by server during sample run.")
                    break
                    
                current_time = time.time()
                latency = current_time - last_packet_time
                last_packet_time = current_time
                
                log_packet(datetime.now(timezone.utc), latency)
            except socket.timeout:
                print("Socket read timeout (no packet received for 5s).")
                break
            
        s.close()
        print("60-second sample session completed cleanly.")
    except Exception as e:
        print(f"Network error during sampling run: {e}")

    generate_graphs()

if __name__ == "__main__":
    run_sample_session()
