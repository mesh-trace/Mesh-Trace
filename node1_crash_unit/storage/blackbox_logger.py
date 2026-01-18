"""
Blackbox data logger
Stores crash data and sensor logs persistently (like aircraft blackbox)
"""

import os
import json
import gzip
import time
from datetime import datetime
from pathlib import Path
from config import BLACKBOX_LOG_PATH, BLACKBOX_MAX_SIZE_MB, BLACKBOX_ROTATION_COUNT


class BlackboxLogger:
    """Persistent logging system for crash data"""
    
    def __init__(self, log_path=None):
        """
        Initialize blackbox logger
        
        Args:
            log_path: Directory path for log files
        """
        self.log_path = log_path or BLACKBOX_LOG_PATH
        self.max_size_bytes = BLACKBOX_MAX_SIZE_MB * 1024 * 1024
        self.rotation_count = BLACKBOX_ROTATION_COUNT
        
        # Ensure log directory exists
        os.makedirs(self.log_path, exist_ok=True)
        
        # Current log file
        self.current_log_file = os.path.join(self.log_path, "blackbox_current.jsonl")
        self.crash_log_file = os.path.join(self.log_path, "crash_events.jsonl")
    
    def _get_log_size(self, filepath):
        """Get size of log file in bytes"""
        if os.path.exists(filepath):
            return os.path.getsize(filepath)
        return 0
    
    def _rotate_log(self, filepath):
        """Rotate log file when it gets too large"""
        if not os.path.exists(filepath):
            return
        
        current_size = self._get_log_size(filepath)
        if current_size < self.max_size_bytes:
            return
        
        # Compress and archive current log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_file = filepath.replace("current", f"archive_{timestamp}").replace(".jsonl", ".jsonl.gz")
        
        try:
            # Compress current log
            with open(filepath, 'rb') as f_in:
                with gzip.open(archive_file, 'wb') as f_out:
                    f_out.writelines(f_in)
            
            # Remove original file
            os.remove(filepath)
            
            # Cleanup old archives (keep only rotation_count most recent)
            self._cleanup_old_archives()
            
            print(f"Log rotated: {archive_file}")
        except Exception as e:
            print(f"Error rotating log: {e}")
    
    def _cleanup_old_archives(self):
        """Remove old log archives beyond rotation count"""
        try:
            # Find all archive files
            archive_files = sorted(
                [f for f in os.listdir(self.log_path) if f.startswith("blackbox_archive_")],
                reverse=True
            )
            
            # Remove files beyond rotation count
            for old_file in archive_files[self.rotation_count:]:
                old_path = os.path.join(self.log_path, old_file)
                os.remove(old_path)
                print(f"Removed old archive: {old_file}")
        except Exception as e:
            print(f"Error cleaning up archives: {e}")
    
    def log(self, data, log_type="sensor"):
        """
        Log data to blackbox
        
        Args:
            data: Dictionary or JSON-serializable data to log
            log_type: Type of log entry (sensor, crash, etc.)
        """
        try:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'type': log_type,
                'data': data
            }
            
            log_line = json.dumps(log_entry) + '\n'
            
            # Append to current log
            with open(self.current_log_file, 'a') as f:
                f.write(log_line)
            
            # Check if rotation is needed
            self._rotate_log(self.current_log_file)
        except Exception as e:
            print(f"Error logging to blackbox: {e}")
    
    def log_crash(self, crash_data):
        """
        Log crash event specifically
        
        Args:
            crash_data: Crash event data dictionary
        """
        try:
            crash_entry = {
                'timestamp': datetime.now().isoformat(),
                'type': 'crash_event',
                'crash_data': crash_data
            }
            
            crash_line = json.dumps(crash_entry) + '\n'
            
            # Append to crash log
            with open(self.crash_log_file, 'a') as f:
                f.write(crash_line)
            
            # Also log to general log
            self.log(crash_data, log_type='crash')
            
            print(f"Crash event logged: {self.crash_log_file}")
        except Exception as e:
            print(f"Error logging crash event: {e}")
    
    def read_recent_logs(self, count=100, log_type=None):
        """
        Read recent log entries
        
        Args:
            count: Number of recent entries to retrieve
            log_type: Filter by log type (optional)
            
        Returns:
            list: List of log entries
        """
        entries = []
        
        try:
            if os.path.exists(self.current_log_file):
                with open(self.current_log_file, 'r') as f:
                    lines = f.readlines()
                    
                    # Filter by type if specified
                    for line in lines[-count:]:
                        entry = json.loads(line.strip())
                        if log_type is None or entry.get('type') == log_type:
                            entries.append(entry)
        except Exception as e:
            print(f"Error reading logs: {e}")
        
        return entries
    
    def read_crash_logs(self, count=50):
        """
        Read recent crash events
        
        Args:
            count: Number of crash events to retrieve
            
        Returns:
            list: List of crash event entries
        """
        entries = []
        
        try:
            if os.path.exists(self.crash_log_file):
                with open(self.crash_log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-count:]:
                        entries.append(json.loads(line.strip()))
        except Exception as e:
            print(f"Error reading crash logs: {e}")
        
        return entries
    
    def close(self):
        """Close logger and cleanup"""
        # Nothing special needed for file-based logging
        pass
