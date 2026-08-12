import socket
import base64
import time
import os
import json
from datetime import datetime, timezone, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# CONFIGURATION
# ==========================================
NTRIP_CASTER = "caster.emlid.com"
NTRIP_PORT = 2101
MOUNTPOINT = "MP25727"
USER = "u33679"
PASSWORD = "376rfe"

GRAPH_SUMMARY_OUTPUT = "ntrip_session_summary.png"
GRAPH_OVERLAY_OUTPUT = "ntrip_overlay_analysis.png"
DROPOUT_THRESHOLD_SEC = 5.5
SAMPLE_DURATION_SEC = 180
LOCAL_TZ = timezone(timedelta(hours=9, minutes=30))

# Environment Secrets from GitHub
GCP_KEY_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
# ==========================================

def get_sheet_client():
    """Authenticates with Google Sheets API using the environment secret."""
    if not GCP_KEY_JSON or not SPREADSHEET_ID:
        raise ValueError("Missing GCP_SERVICE_ACCOUNT_KEY or SPREADSHEET_ID environment variables.")
    
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_dict = json.loads(GCP_KEY_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    
    # Initialize Header Row if empty
    if not sheet.get_all_values():
        sheet.append_row(["timestamp_utc", "latency_sec"])
        
    return sheet

def generate_graphs(sheet):
    """Fetches recent data directly from Google Sheets to render PNG plots."""
    try:
        records = sheet.get_all_records()
    except Exception as e:
        print(f"Failed to fetch records from Google Sheets: {e}")
        return

    if not records:
        print("No data available in Google Sheet to generate plots.")
        return

    sessions = {}
    for row in records:
        if row.get("timestamp_utc") and row.get("latency_sec"):
            dt_utc = datetime.fromisoformat(str(row["timestamp_utc"]))
            dt_local = dt_utc.astimezone(LOCAL_TZ)
            latency = float(row["latency_sec"])

            session_key = dt_local.replace(minute=(dt_local.minute // 10) * 10, second=0, microsecond=0)
            if session_key not in sessions:
                sessions[session_key] = []
            sessions[session_key].append((dt_local, latency))

    if not sessions:
        return

    # --- GRAPH 1: TIMELINE SUMMARY ---
    session_times = []
    avg_latencies = []
    max_latencies = []
    has_dropout = []

    for s_time in sorted(sessions.keys()):
        recs = sessions[s_time]
        lats = [r[1] for r in recs]
        
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

    ax_summary.set_title(f"NTRIP Stream 10-Min Timeline (Google Sheets Sync)\nSamples: {len(sessions)} | Dropouts: {sum(has_dropout)}")
    ax_summary.set_xlabel("Local Time (UTC+9:30)")
    ax_summary.set_ylabel("Packet Interval (Seconds)")
    ax_summary.legend(loc='upper right')
    ax_summary.grid(True, linestyle=':', alpha=0.6)
    plt.xticks(rotation=45)
    plt.tight_layout()

    plt.savefig(GRAPH_SUMMARY_OUTPUT)
    plt.close(fig_summary)

    # --- GRAPH 2: OVERLAY ANALYSIS ---
    fig_overlay, ax_overlay = plt.subplots(figsize=(12, 6))
    ax_overlay.axhline(y=1.0, color='g', linestyle='--', alpha=0.5, label='Ideal Latency (1.0s)')
    ax_overlay.axhline(y=DROPOUT_THRESHOLD_SEC, color='r', linestyle='--', alpha=0.5, label='Dropout Limit (2.5s)')

    for s_time in sorted(sessions.keys()):
        recs = sessions[s_time]
        if not recs:
            continue
        start_dt = recs[0][0]
        relative_seconds = [(r[0] - start_dt).total_seconds() for r in recs]
        latencies = [r[1] for r in recs]

        ax_overlay.plot(relative_seconds, latencies, linestyle='-', linewidth=1, alpha=0.35)

    ax_overlay.set_title(f"NTRIP 60-Second Overlay Analysis ({len(sessions)} Combined Runs)")
    ax_overlay.set_xlabel("Elapsed Time Within Sample Window (Seconds)")
    ax_overlay.set_ylabel("Packet Interval (Seconds)")
    ax_overlay.legend(loc='upper right')
    ax_overlay.grid(True, linestyle=':', alpha=0.6)
    plt.tight_layout()

    plt.savefig(GRAPH_OVERLAY_OUTPUT)
    plt.close(fig_overlay)

def run_sample_session():
    sheet = get_sheet_client()
    
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
    batch_rows = []
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((NTRIP_CASTER, NTRIP_PORT))
        s.sendall(request.encode('utf-8'))
        
        response = s.recv(1024).decode('utf-8', errors='ignore')
        if "200 OK" not in response and "ICY" not in response:
            s.close()
            generate_graphs(sheet)
            return

        s.settimeout(5)
        last_packet_time = time.time()

        while time.time() - session_start < SAMPLE_DURATION_SEC:
            try:
                data = s.recv(4096)
                if not data:
                    break
                    
                current_time = time.time()
                latency = current_time - last_packet_time
                last_packet_time = current_time
                
                # Append row in memory batch
                batch_rows.append([datetime.now(timezone.utc).isoformat(), latency])
            except socket.timeout:
                break
            
        s.close()
    except Exception as e:
        print(f"Network sampling error: {e}")

    # Push batch directly to Google Sheets in one single API request
    if batch_rows:
        sheet.append_rows(batch_rows)
        print(f"Uploaded {len(batch_rows)} records to Google Sheets.")

    generate_graphs(sheet)

if __name__ == "__main__":
    run_sample_session()
