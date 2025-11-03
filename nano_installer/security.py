import re
import subprocess
from pathlib import Path
import hashlib
import shutil
import tempfile
import time
import datetime
import requests
from nano_installer.config import VT_API_KEY

# --- Configuration for AI Security Scanner ---
# VT_API_KEY is loaded from nano_installer.config

# Import WorkerThread from utils (will be created next)
# from .utils import WorkerThread

def calculate_file_hash(filepath, algorithm='sha256', worker=None):
    """Calculates the hash of a file with progress updates."""
    hasher = hashlib.new(algorithm)
    file_path = Path(filepath)
    file_size = file_path.stat().st_size
    bytes_read = 0

    with open(file_path, "rb") as f:
        while True:
            if worker and not worker.is_running():
                raise InterruptedError("Hashing was cancelled.")
            
            chunk = f.read(4096)
            if not chunk:
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
            if worker:
                worker.progress.emit({"type": "hash_progress", "progress": int((bytes_read / file_size) * 100)})
    return hasher.hexdigest()

def scan_offline(filepath, worker=None):
    """Performs a basic offline security scan of a .deb file."""
    if worker: worker.progress.emit({"line": "Performing basic offline heuristic scan..."})
    time.sleep(1) # Give user time to read the message

    file_path = Path(filepath)
    findings = []

    # Suspicious commands to look for in maintainer scripts
    SUSPICIOUS_COMMANDS = [
        'curl', 'wget', 'nc', 'netcat', 'base64', 'python', 'perl', 'ruby',
        'rm -rf', 'mkfs', 'shutdown', 'reboot', 'nohup', 'crontab',
        'systemctl start', 'systemctl enable', 'useradd', 'usermod', 'groupadd',
        'add-apt-repository'
    ]

    # Suspicious installation paths. We check if files are installed *inside* these.
    SUSPICIOUS_PATHS = ['/home', '/root', '/tmp', '/var/tmp']

    temp_dir = tempfile.mkdtemp(prefix="nano-installer-scan-")
    try:
        # 1. Extract the package contents
        if worker: worker.progress.emit({"line": "Extracting package for analysis..."})
        extract_cmd = ["dpkg-deb", "-R", str(file_path), temp_dir]
        # We capture output to show on error
        proc = subprocess.run(extract_cmd, check=True, capture_output=True, text=True)

        # 2. Analyze maintainer scripts (preinst, postinst, etc.)
        if worker: worker.progress.emit({"line": "Analyzing maintainer scripts..."})
        debian_dir = Path(temp_dir) / "DEBIAN"
        if debian_dir.is_dir():
            for script_name in ["preinst", "postinst", "prerm", "postrm"]:
                script_path = debian_dir / script_name
                if script_path.is_file():
                    try:
                        content = script_path.read_text(encoding='utf-8', errors='ignore')
                        for command in SUSPICIOUS_COMMANDS:
                            # Use regex to find command as a whole word
                            if re.search(r'(^|\s|/)' + re.escape(command) + r'(\s|;|\||&|$)', content):
                                findings.append(f"Suspicious command '{command}' found in '{script_name}' script.")
                    except Exception:
                        findings.append(f"Could not read or parse the '{script_name}' script.")

        # 3. Analyze file paths and permissions
        if worker: worker.progress.emit({"line": "Analyzing file paths and permissions..."})
        content_root = Path(temp_dir)
        # We need to ignore the DEBIAN directory itself from this analysis
        for item in content_root.rglob('*'):
            if "DEBIAN" in item.parts:
                continue

            relative_path = item.relative_to(content_root)
            install_path_str = f"/{relative_path}"
            for suspicious_path in SUSPICIOUS_PATHS:
                if install_path_str.startswith(suspicious_path + '/'):
                    findings.append(f"File '{relative_path}' is installed to a suspicious location: {install_path_str}")
                    break # Don't report the same file multiple times

            # Check for setuid/setgid bits on executables
            if item.is_file() and not item.is_symlink() and (item.stat().st_mode & 0o111): # is executable
                st_mode = item.stat().st_mode
                if st_mode & 0o4000: # SUID
                    findings.append(f"Executable '{relative_path}' has SUID bit set.")
                if st_mode & 0o2000: # SGID
                    findings.append(f"Executable '{relative_path}' has SGID bit set.")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_output = e.stderr if hasattr(e, 'stderr') else str(e)
        return f"Offline Scan Failed for: {file_path.name}\nCould not extract package for analysis.\n\nDetails: {error_output}"
    finally:
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir)

    # 4. Format the report
    result_str = f"Offline Scan Complete for: {file_path.name}\n================================\nMethod: Basic Heuristic Analysis (Offline)\n--------------------------------\n"
    if not findings:
        result_str += "Result: Clean (No obvious suspicious indicators found)\n--------------------------------\nThis basic offline scan did not find any common red flags.\nFor a more thorough analysis, connect to the internet to use VirusTotal."
    else:
        unique_findings = sorted(list(set(findings)))
        result_str += f"Result: SUSPICIOUS ({len(unique_findings)} potential issues found)\n--------------------------------\nThe following potential issues were found. Review them carefully:\n\n"
        for i, finding in enumerate(unique_findings, 1):
            result_str += f" {i}. {finding}\n"
        result_str += "\nThese findings are based on heuristics and may be false positives.\nProceed with caution."
    return result_str

def scan_with_virustotal(filepath, worker=None):
    """Scans a file with VirusTotal by its hash to avoid uploading, and returns a formatted result string."""
    try:
        if not VT_API_KEY:
            raise ValueError("VirusTotal API key is not configured. Please set the NANO_VT_API_KEY environment variable.")

        headers = {"x-apikey": VT_API_KEY}
        file_path = Path(filepath)

        # 1. Calculate the file's SHA-256 hash
        worker.progress.emit({"line": f"Calculating hash for {file_path.name}..."})
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read and update hash in chunks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                if worker and not worker.is_running():
                    # Assuming WorkerThread is available in the scope where this is called
                    raise InterruptedError("Scan was cancelled.")
                sha256_hash.update(byte_block)
        file_hash = sha256_hash.hexdigest()

        # 2. Query VirusTotal for a report using the hash
        worker.progress.emit({"line": "Querying VirusTotal database..."})
        report_url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
        report_res = requests.get(report_url, headers=headers, timeout=30)

        # 3. Handle the response
        if report_res.status_code == 404:
            # File is unknown to VirusTotal, which is suspicious but not necessarily dangerous.
            result_str = f"Scan Complete for: {file_path.name}\n"
            result_str += "================================\n"
            result_str += "Result: SUSPICIOUS (File not found in VirusTotal database)\n"
            result_str += "--------------------------------\n"
            result_str += "This file has not been scanned by VirusTotal before. This can be normal for new or rare software, but exercise caution.\n"
            return result_str

        report_res.raise_for_status()  # Raise an exception for other errors (e.g., 401, 500)
        report_data = report_res.json()["data"]["attributes"]

        # 4. Format the results from the existing report
        stats = report_data.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        harmless = stats.get("harmless", 0)
        undetected = stats.get("undetected", 0)
        total = malicious + suspicious + harmless + undetected

        result_str = f"Scan Complete for: {file_path.name}\n"
        result_str += "================================\n"
        if malicious > 0: result_str += f"Result: DANGER! ({malicious}/{total} engines detected threats)\n"
        elif suspicious > 0: result_str += f"Result: SUSPICIOUS ({suspicious}/{total} engines flagged as suspicious)\n"
        else: result_str += f"Result: Clean ({harmless + undetected}/{total} engines found no threats)\n"
        result_str += "--------------------------------\n"
        result_str += f"Malicious: {malicious}\nSuspicious: {suspicious}\nHarmless: {harmless}\nUndetected: {undetected}\n"

        if 'last_analysis_date' in report_data:
            last_scan_ts = report_data['last_analysis_date']
            last_scan_dt = datetime.datetime.fromtimestamp(last_scan_ts, tz=datetime.timezone.utc)
            result_str += f"\nLast Scanned by VirusTotal: {last_scan_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

        return result_str
    except requests.exceptions.RequestException:
        if worker: worker.progress.emit({"line": "VirusTotal unavailable. Falling back to offline scan..."})
        return scan_offline(filepath, worker=worker)
    except ValueError as e:
        raise ValueError(str(e)) from e
