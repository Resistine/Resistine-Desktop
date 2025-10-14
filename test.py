#!/usr/bin/env python3
"""
VPN Test UI for Resistine Desktop
=================================
A simple test interface for testing the Python integration with the privileged daemon.
This UI allows testing VPN start/stop operations and status checking.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import os
import threading
import time
from pathlib import Path

# Import the Python wrapper functions
import subprocess, shlex, os, sys, json

# Production-safe SMAppService calls from Python (PyObjC)
try:
    import objc  # pyobjc
    from ServiceManagement import SMAppService  # pyobjc-framework-ServiceManagement
except Exception:
    objc = None
    SMAppService = None

_STATUS_MAP = {0: "notRegistered", 1: "enabled", 2: "requiresApproval", 3: "notFound"}
plist_name = "com.resistine.plist"

def _get_daemon_service():
    """Return SMAppService instance for the daemon, handling API name variants."""
    if SMAppService is None:
        return None
    # Try modern Objective-C selector first (daemonServiceWithPlistName:)
    ctor = getattr(SMAppService, 'daemonServiceWithPlistName_', None)
    if callable(ctor):
        try:
            return ctor(plist_name)
        except Exception:
            pass
    # Fallback to older/alternate selector (daemonWithPlistName:)
    ctor = getattr(SMAppService, 'daemonWithPlistName_', None)
    if callable(ctor):
        try:
            return ctor(plist_name)
        except Exception:
            pass
    # Last resort: some bindings expose a generic 'daemon_' taking keyword
    ctor = getattr(SMAppService, 'daemon_', None)
    if callable(ctor):
        try:
            return ctor(plistName=plist_name)
        except Exception:
            pass
    return None

def sm_status():
    if SMAppService is None:
        return "unknown"
    service = _get_daemon_service()
    if service is None:
        return "unknown"
    try:
        return _STATUS_MAP.get(int(service.status()), "unknown")
    except Exception:
        return "unknown"

def sm_register():
    if SMAppService is None:
        return "unknown"
    service = _get_daemon_service()
    if service is None:
        return "unknown"
    try:
        _ = service.registerAndReturnError_(None)
    except Exception:
        pass
    s = sm_status()
    if s == "requiresApproval":
        SMAppService.openSystemSettingsLoginItems()
    return s

def sm_unregister(block=True, timeout=10.0):
    if SMAppService is None:
        return Exception("ServiceManagement not available")
    service = _get_daemon_service()
    if service is None:
        return Exception("SMAppService daemon constructor not available")
    done = threading.Event()
    errbox = {"err": None}

    def _done(err):
        errbox["err"] = err
        done.set()

    service.unregisterWithCompletionHandler_(_done)
    if block:
        done.wait(timeout=timeout)
    return errbox["err"]  # None means success

def _candidate_cli_paths():
    here = os.path.dirname(__file__)
    # Dev path
    yield os.path.join(here, "apple_helper/cli/ResistCli")
    # If frozen inside .app
    if getattr(sys, 'frozen', False):
        macos_dir = os.path.dirname(sys.executable)
        app_contents = os.path.abspath(os.path.join(macos_dir, ".."))
        # Preferred: Contents/Resources/ResistCli
        yield os.path.join(app_contents, "Library", "LaunchServices", "ResistCli")
        
       

def _resolve_cli_path():
    # Allow override via env
    override = os.environ.get("RESISTINE_CLI")
    if override and os.path.exists(override):
        return override
    for p in _candidate_cli_paths():
        if os.path.exists(p):
            return p
    return None

CLI = _resolve_cli_path()

def _run_cli(*args):
    if not CLI:
        # Mimic 'notFound' for auth-status to avoid crashing UI
        completed = type('R', (), {})()
        completed.stdout = "notFound"
        completed.stderr = ""
        completed.returncode = 4
        return completed
    return subprocess.run([CLI, *args], text=True, capture_output=True)

    

def start_vpn(cfg):
    """Start VPN using the CLI wrapper"""
    r = subprocess.run([CLI, "start-vpn", cfg], text=True, capture_output=True)
    return (r.returncode == 0, r.stdout.strip() or r.stderr.strip())

def stop_vpn(cfg):
    """Stop VPN using the CLI wrapper"""
    r = subprocess.run([CLI, "stop-vpn", cfg], text=True, capture_output=True)
    return (r.returncode == 0, r.stdout.strip() or r.stderr.strip())

def status(iface, test_ip=None):
    """Check VPN status using the CLI wrapper"""
    print(f"🔍 [STATUS] Checking status for interface: {iface}")
    if test_ip:
        print(f"🌐 [PING] Test IP provided: {test_ip}")
    else:
        print(f"🌐 [PING] No test IP provided - will only check interface status")
    
    args = [CLI, "status", iface] + ([test_ip] if test_ip else [])
    print(f"🚀 [COMMAND] Running: {' '.join(args)}")
    
    r = subprocess.run(args, text=True, capture_output=True)
    
    print(f"📊 [RESULT] Return code: {r.returncode}")
    print(f"📤 [STDOUT] {r.stdout.strip()}")
    if r.stderr.strip():
        print(f"📤 [STDERR] {r.stderr.strip()}")
    
    success = r.returncode == 0
    output = r.stdout.strip() or r.stderr.strip()
    
    if success:
        if "Running" in output:
            print(f"✅ [STATUS] VPN is Running")
        else:
            print(f"❌ [STATUS] VPN is Stopped")
    else:
        print(f"❌ [STATUS] Status check failed")
    
    return (success, output)

def test_ping_connectivity(ip_address, count=3):
    """Test ping connectivity to a specific IP address"""
    print(f"🌐 [PING-TEST] Testing connectivity to: {ip_address}")
    print(f"🌐 [PING-TEST] Ping count: {count}")
    
    try:
        # Use ping command with specific parameters
        cmd = ["ping", "-c", str(count), "-W", "2000", ip_address]
        print(f"🚀 [PING-TEST] Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        print(f"📊 [PING-TEST] Return code: {result.returncode}")
        print(f"📤 [PING-TEST] STDOUT: {result.stdout}")
        if result.stderr:
            print(f"📤 [PING-TEST] STDERR: {result.stderr}")
        
        if result.returncode == 0:
            print(f"✅ [PING-TEST] Ping successful to {ip_address}")
            return True, result.stdout
        else:
            print(f"❌ [PING-TEST] Ping failed to {ip_address}")
            return False, result.stderr or result.stdout
            
    except subprocess.TimeoutExpired:
        print(f"⏰ [PING-TEST] Ping timed out to {ip_address}")
        return False, "Ping timed out"
    except Exception as e:
        print(f"❌ [PING-TEST] Ping error: {e}")
        return False, str(e)

def test_dns_resolution(hostname):
    """Test DNS resolution for a hostname"""
    print(f"🌐 [DNS-TEST] Testing DNS resolution for: {hostname}")
    
    try:
        # Use nslookup command
        cmd = ["nslookup", hostname]
        print(f"🚀 [DNS-TEST] Running: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        print(f"📊 [DNS-TEST] Return code: {result.returncode}")
        print(f"📤 [DNS-TEST] STDOUT: {result.stdout}")
        if result.stderr:
            print(f"📤 [DNS-TEST] STDERR: {result.stderr}")
        
        if result.returncode == 0:
            print(f"✅ [DNS-TEST] DNS resolution successful for {hostname}")
            return True, result.stdout
        else:
            print(f"❌ [DNS-TEST] DNS resolution failed for {hostname}")
            return False, result.stderr or result.stdout
            
    except subprocess.TimeoutExpired:
        print(f"⏰ [DNS-TEST] DNS lookup timed out for {hostname}")
        return False, "DNS lookup timed out"
    except Exception as e:
        print(f"❌ [DNS-TEST] DNS lookup error: {e}")
        return False, str(e)


class VPNTestUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Resistine VPN Test Interface")
        self.root.geometry("800x600")
        self.root.configure(bg='#2e2e2e')
        
        # Current config file
        self.current_config = None
        self.current_interface = None
        
        # Status update thread
        self.status_thread = None
        self.running = True
        
        self.setup_ui()
        
        # Initial helper status
        self.update_helper_status()
        self.start_status_updates()
        if sm_status() == "enabled":
            sm_unregister()
            self.log_message("Helper unregistered")
        
    def setup_ui(self):
        """Setup the main UI components"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Resistine VPN Test Interface", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Configuration file selection
        ttk.Label(main_frame, text="Config File:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.config_var = tk.StringVar()
        self.config_entry = ttk.Entry(main_frame, textvariable=self.config_var, width=50)
        self.config_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 5), pady=5)
        ttk.Button(main_frame, text="Browse", command=self.browse_config).grid(row=1, column=2, pady=5)
        
        # Interface name
        ttk.Label(main_frame, text="Interface:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.interface_var = tk.StringVar()
        self.interface_entry = ttk.Entry(main_frame, textvariable=self.interface_var, width=20)
        self.interface_entry.grid(row=2, column=1, sticky=tk.W, padx=(5, 0), pady=5)
        
        # Test IP (optional)
        ttk.Label(main_frame, text="Test IP:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.test_ip_var = tk.StringVar(value="8.8.8.8")
        self.test_ip_entry = ttk.Entry(main_frame, textvariable=self.test_ip_var, width=20)
        self.test_ip_entry.grid(row=3, column=1, sticky=tk.W, padx=(5, 0), pady=5)
        
        # Control buttons frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=4, column=0, columnspan=3, pady=20)
        
        # VPN control buttons
        self.start_btn = ttk.Button(control_frame, text="Start VPN", command=self.start_vpn, 
                                   style='Accent.TButton')
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="Stop VPN", command=self.stop_vpn)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        self.status_btn = ttk.Button(control_frame, text="Check Status", command=self.check_status)
        self.status_btn.pack(side=tk.LEFT, padx=5)
        
        self.refresh_btn = ttk.Button(control_frame, text="Refresh", command=self.refresh_status)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)
        
        # Connectivity test buttons
        self.ping_btn = ttk.Button(control_frame, text="Test Ping", command=self.test_ping)
        self.ping_btn.pack(side=tk.LEFT, padx=5)
        
        self.dns_btn = ttk.Button(control_frame, text="Test DNS", command=self.test_dns)
        self.dns_btn.pack(side=tk.LEFT, padx=5)
        
        # Helper/Authorization controls
        helper_frame = ttk.LabelFrame(main_frame, text="Helper Authorization", padding="10")
        helper_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        helper_frame.columnconfigure(1, weight=1)

        ttk.Label(helper_frame, text="Daemon status:").grid(row=0, column=0, sticky=tk.W)
        self.helper_status_var = tk.StringVar(value="checking…")
        self.helper_status_lbl = ttk.Label(helper_frame, textvariable=self.helper_status_var)
        self.helper_status_lbl.grid(row=0, column=1, sticky=tk.W)

        ttk.Button(helper_frame, text="Register Helper", command=self.register_helper).grid(row=0, column=2, padx=5)
        ttk.Button(helper_frame, text="Open Login Items", command=self.open_login_items).grid(row=0, column=3, padx=5)

        # Status display
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(0, weight=1)
        
        self.status_text = scrolledtext.ScrolledText(status_frame, height=15, width=80)
        self.status_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Auto-refresh checkbox
        self.auto_refresh_var = tk.BooleanVar(value=True)
        auto_refresh_cb = ttk.Checkbutton(main_frame, text="Auto-refresh status (every 5s)", 
                                         variable=self.auto_refresh_var)
        auto_refresh_cb.grid(row=7, column=0, columnspan=3, pady=5)
        
        # Log initial status
        self.log_message("VPN Test Interface initialized")
        self.log_message(f"CLI Path: {CLI}")
        cli_exists = os.path.exists(CLI) if CLI else False
        self.log_message(f"CLI Exists: {cli_exists}")
        if not cli_exists:
            self.log_message("⚠️ CLI not found in app bundle. Expected at Contents/Resources/ResistCli. Some actions will be disabled until present.")
        
    def browse_config(self):
        """Browse for WireGuard configuration file"""
        filename = filedialog.askopenfilename(
            title="Select WireGuard Config File",
            filetypes=[("Config files", "*.conf"), ("All files", "*.*")]
        )
        if filename:
            # Get the proper app support directory
            from plugins.vpn.main import get_writable_wireguard_dir
            wireguard_folder = get_writable_wireguard_dir()
            destination_path = os.path.join(wireguard_folder, os.path.basename(filename))
            
            # Copy the config file to the proper location
            try:
                with open(filename, 'rb') as src_file:
                    with open(destination_path, 'wb') as dst_file:
                        dst_file.write(src_file.read())
                print(f"✅ Config copied to: {destination_path}")
                self.log_message(f"✅ Config copied to app support directory")
            except Exception as e:
                print(f"❌ Failed to copy config: {e}")
                self.log_message(f"❌ Failed to copy config: {e}")
                return
            
            # Use the destination path instead of the original
            self.config_var.set(destination_path)
            # Auto-extract interface name from filename
            interface_name = Path(filename).stem
            self.interface_var.set(interface_name)
            self.current_config = destination_path  # Use the copied file path
            self.current_interface = interface_name
            self.log_message(f"Selected config: {destination_path}")
            self.log_message(f"Interface: {interface_name}")
    
    def log_message(self, message):
        """Add a message to the status log"""
        timestamp = time.strftime("%H:%M:%S")
        self.status_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.status_text.see(tk.END)
        self.root.update_idletasks()
        
    def update_helper_status(self):
        status = sm_status()
        self.helper_status_var.set(status)
        self.log_message(f"Helper status: {status}")

    def register_helper(self):
        self.log_message("🔧 Starting daemon registration process...")
        status = sm_register()
        self.log_message(f"📊 Status after registration: {status}")
        self.update_helper_status()

    def open_login_items(self):
        self.log_message("Opening System Settings → Login Items…")
        if SMAppService is not None:
            SMAppService.openSystemSettingsLoginItems()
    
    def start_vpn(self):
        """Start VPN connection"""
        if not self.current_config:
            messagebox.showerror("Error", "Please select a configuration file first")
            return
        # Ensure helper authorized
        helper_state = sm_status()
        if helper_state != "enabled":
            self.log_message(f"Helper not enabled (status={helper_state}). Attempting register…")
            self.register_helper()
            return
        
        self.log_message("Starting VPN...")
        self.start_btn.config(state='disabled')
        
        def start_thread():
            try:
                success, output = start_vpn(self.current_config)
                if success or output:
                    # Parse output to extract actual interface name (e.g., "utun6" from "[+] Interface for wg0 is utun6")
                    import re
                    match = re.search(r'Interface for \S+ is (\S+)', output)
                    if match:
                        actual_interface = match.group(1)
                        self.current_interface = actual_interface
                        self.log_message(f"ℹ️ Mapped to actual interface: {actual_interface}")
                    
                    # Poll status up to 15s until interface reports up
                    test_ip = self.test_ip_var.get() if self.test_ip_var.get() else None
                    poll_ok = False
                    poll_output = ""
                    for _ in range(15):
                        s_ok, s_out = status(self.current_interface, test_ip)
                        if s_ok and "Running" in s_out:
                            poll_ok = True
                            poll_output = s_out
                            break
                        time.sleep(1)
                    if poll_ok:
                        self.log_message(f"✅ VPN started. Status: {poll_output}")
                    else:
                        self.log_message(f"⚠️ VPN start output: {output}")
                        self.log_message(f"⚠️ Status check: {poll_output}")
                else:
                    self.log_message(f"❌ Failed to start VPN: {output}")
            except Exception as e:
                self.log_message(f"❌ Exception starting VPN: {e}")
            finally:
                self.start_btn.config(state='normal')
        
        threading.Thread(target=start_thread, daemon=True).start()
    
    def stop_vpn(self):
        """Stop VPN connection"""
        if not self.current_config:
            messagebox.showerror("Error", "Please select a configuration file first")
            return
        helper_state = sm_status()
        if helper_state != "enabled":
            self.log_message(f"Helper not enabled (status={helper_state}).")
            return
        
        self.log_message("Stopping VPN...")
        self.stop_btn.config(state='disabled')
        
        def stop_thread():
            try:
                success, output = stop_vpn(self.current_config)
                if success or output:
                    self.log_message(f"ℹ️ Stop VPN output: {output}")
                    # Poll until status reports down (up to 15s)
                    test_ip = self.test_ip_var.get() if self.test_ip_var.get() else None
                    poll_down = False
                    poll_output = ""
                    for _ in range(15):
                        s_ok, s_out = status(self.current_interface, test_ip)
                        if "Stopped" in s_out or "down" in s_out.lower():
                            poll_down = True
                            poll_output = s_out
                            break
                        time.sleep(1)
                    if poll_down:
                        self.log_message(f"✅ VPN stopped. Status: {poll_output}")
                    else:
                        self.log_message(f"⚠️ VPN may still be running. Status: {poll_output}")
                else:
                    self.log_message(f"❌ Failed to stop VPN: {output}")
            except Exception as e:
                self.log_message(f"❌ Exception stopping VPN: {e}")
            finally:
                self.stop_btn.config(state='normal')
        
        threading.Thread(target=stop_thread, daemon=True).start()
    
    def check_status(self):
        """Check VPN status"""
        if not self.current_interface:
            messagebox.showerror("Error", "Please specify an interface name")
            return
        
        self.log_message("Checking VPN status...")
        print(f"🔍 [MANUAL-STATUS] Manual status check requested for: {self.current_interface}")
        self.status_btn.config(state='disabled')
        
        def status_thread():
            try:
                test_ip = self.test_ip_var.get() if self.test_ip_var.get() else None
                print(f"🔍 [MANUAL-STATUS] Test IP: {test_ip}")
                print(f"🔍 [MANUAL-STATUS] Calling status function...")
                
                success, output = status(self.current_interface, test_ip)
                
                print(f"🔍 [MANUAL-STATUS] Status function returned: success={success}, output='{output}'")
                
                if success:
                    self.log_message(f"✅ Status: {output}")
                    print(f"✅ [MANUAL-STATUS] Status check successful: {output}")
                else:
                    self.log_message(f"❌ Status check failed: {output}")
                    print(f"❌ [MANUAL-STATUS] Status check failed: {output}")
            except Exception as e:
                self.log_message(f"❌ Exception checking status: {e}")
                print(f"❌ [MANUAL-STATUS] Exception: {e}")
            finally:
                self.status_btn.config(state='normal')
                print(f"🔍 [MANUAL-STATUS] Manual status check completed")
        
        threading.Thread(target=status_thread, daemon=True).start()
    
    def refresh_status(self):
        """Refresh VPN status"""
        self.check_status()
    
    def test_ping(self):
        """Test ping connectivity to the test IP"""
        test_ip = self.test_ip_var.get()
        if not test_ip:
            messagebox.showerror("Error", "Please enter a test IP address")
            return
        
        self.log_message(f"Testing ping connectivity to {test_ip}...")
        self.ping_btn.config(state='disabled')
        
        def ping_thread():
            try:
                success, output = test_ping_connectivity(test_ip)
                if success:
                    self.log_message(f"✅ Ping successful to {test_ip}")
                    self.log_message(f"Ping output: {output}")
                else:
                    self.log_message(f"❌ Ping failed to {test_ip}")
                    self.log_message(f"Ping error: {output}")
            except Exception as e:
                self.log_message(f"❌ Exception during ping test: {e}")
            finally:
                self.ping_btn.config(state='normal')
        
        threading.Thread(target=ping_thread, daemon=True).start()
    
    def test_dns(self):
        """Test DNS resolution"""
        # Test DNS resolution for a common hostname
        hostname = "dashboard.resisti.net"  # You can change this to any hostname you want to test
        
        self.log_message(f"Testing DNS resolution for {hostname}...")
        self.dns_btn.config(state='disabled')
        
        def dns_thread():
            try:
                success, output = test_dns_resolution(hostname)
                if success:
                    self.log_message(f"✅ DNS resolution successful for {hostname}")
                    self.log_message(f"DNS output: {output}")
                else:
                    self.log_message(f"❌ DNS resolution failed for {hostname}")
                    self.log_message(f"DNS error: {output}")
            except Exception as e:
                self.log_message(f"❌ Exception during DNS test: {e}")
            finally:
                self.dns_btn.config(state='normal')
        
        threading.Thread(target=dns_thread, daemon=True).start()
    
    def start_status_updates(self):
        """Start automatic status updates"""
        def update_loop():
            while self.running:
                if self.auto_refresh_var.get() and self.current_interface:
                    try:
                        test_ip = self.test_ip_var.get() if self.test_ip_var.get() else None
                        print(f"🔄 [AUTO-REFRESH] Starting status check for {self.current_interface}")
                        if test_ip:
                            print(f"🔄 [AUTO-REFRESH] Using test IP: {test_ip}")
                        
                        success, output = status(self.current_interface, test_ip)
                        
                        if success:
                            self.log_message(f"🔄 Auto-refresh: {output}")
                            print(f"🔄 [AUTO-REFRESH] Success: {output}")
                        else:
                            self.log_message(f"🔄 Auto-refresh failed: {output}")
                            print(f"🔄 [AUTO-REFRESH] Failed: {output}")
                    except Exception as e:
                        self.log_message(f"🔄 Auto-refresh error: {e}")
                        print(f"🔄 [AUTO-REFRESH] Exception: {e}")
                else:
                    if not self.auto_refresh_var.get():
                        print(f"🔄 [AUTO-REFRESH] Auto-refresh disabled")
                    if not self.current_interface:
                        print(f"🔄 [AUTO-REFRESH] No interface selected")
                
                print(f"🔄 [AUTO-REFRESH] Sleeping for 15 seconds...")
                time.sleep(15)
        
        self.status_thread = threading.Thread(target=update_loop, daemon=True)
        self.status_thread.start()
    def on_closing(self):
        """Handle window closing"""
        self.running = False
        self.root.destroy()

def main():
    """Main function to run the test UI"""
    root = tk.Tk()
    
    # Configure style
    style = ttk.Style()
    style.theme_use('clam')
    
    # Create the UI
    app = VPNTestUI(root)
    
    # Handle window closing
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    # Start the GUI
    root.mainloop()

if __name__ == "__main__":
    main()
