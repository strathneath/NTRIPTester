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
NTRIP_CASTER = "www.smartnetaus.com"
NTRIP_PORT = 15151
MOUNTPOINT = "MSM_CRYB"
USER = "FyfeSA"
PASSWORD = "0110"

LOG_FILE = "ntrip_reliability_log.csv"
GRAPH_OUTPUT = "ntrip_session_summary.png"
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

def generate_summary_graph():
    """Read full historical CSV data and render the updated summary PNG."""
    if not os.path.exists(LOG_FILE):
        print("No log file found yet. Skipping graph generation.")
        return

    timestamps_utc = []
    latencies = []

    try:
        with open(LOG_FILE, mode='r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("timestamp_utc") and row.get("latency_sec"):
                    timestamps_utc.append(datetime.fromisoformat(row["timestamp_utc"]))
                    latencies.append(float(row["latency_sec"]))
    except Exception as e:
        print(f"Error reading log file: {e}")
        return

    if not timestamps_utc:
        print("Log file contains no data yet. Skipping graph generation.")
        return

    fig_final, ax_final = plt.subplots(figsize=(12, 6))
    ax_final.axhline(y=1.0, color='g', linestyle='--', alpha=0.5, label='Ideal Latency (1.0s)')
    ax_final.axhline(y=DROPOUT_THRESHOLD_SEC, color='r', linestyle='--', alpha=0.5, label='Dropout Limit')

    plot_times_utc = [timestamps_utc[0]]
    plot_latencies = [latencies[0]]
    dropout_shading_triggered = False
    total_gaps = 0

    for i in range(1, len(timestamps_utc)):
        gap = (timestamps_utc[i] - timestamps_utc[i-1]).total_seconds()
        
        if gap > DROPOUT_THRESHOLD_SEC:
            t_start_local = timestamps_utc[i-1].astimezone(LOCAL_TZ)
            t_end_local = timestamps_utc[i].astimezone(LOCAL_TZ)
            
            label = "Missing Data Gap" if not dropout_shading_triggered else ""
            ax_final.axvspan(t_start_local, t_end_local, color='red', alpha=0.2, label=label)
            dropout_shading_triggered = True
            total_gaps += 1
            
            plot_times_utc.append(timestamps_utc[i-1] + timedelta(microseconds=1))
            plot_latencies.append(None)
            
        plot_times_utc.append(timestamps_utc[i])
        plot_latencies.append(latencies[i])

    plot_times_local = [
        dt.astimezone(LOCAL_TZ) if isinstance(dt, datetime) else dt 
        for dt in plot_times_utc
    ]

    ax_final.plot(plot_times_local, plot_latencies, color='#2ca02c', linestyle='-', alpha=0.8, label='Stream Latency')

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    ax_final.set_title(f"NTRIP Reliability Log (Local Time UTC+9:30)\nAvg Interval: {avg_latency:.2f}s | Max Delay: {max_latency:.2f}s | Gaps: {total_gaps}")
    ax_final.set_xlabel("Local Time")
    ax_final.set_ylabel("Packet Interval (Seconds)")
    ax_final.legend(loc='upper right')
    ax_final.grid(True, linestyle=':', alpha=0.6)
    plt.xticks(rotation=45)
    plt.tight_layout()

    plt.savefig(GRAPH_OUTPUT)
    plt.close(fig_final)
    print(f"Graph successfully rendered and saved to {GRAPH_OUTPUT}")

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
            generate_summary_graph()
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

    generate_summary_graph()

if __name__ == "__main__":
    run_sample_session()
