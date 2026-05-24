#!/usr/bin/env python3
import subprocess, threading, time, re, os, sys, signal, json, atexit
from pathlib import Path

TOGGLE_SCRIPT = Path("/tmp/dofus_toggle.sh")
CYCLE_SCRIPT  = Path("/tmp/dofus_cycle.sh")
DAEMON_PID_FILE = Path("/tmp/dofus_daemon.pid")

def create_shortcut_scripts():
    TOGGLE_SCRIPT.write_text("#!/bin/bash\npkill -SIGUSR1 -F {}\n".format(DAEMON_PID_FILE))
    CYCLE_SCRIPT.write_text("#!/bin/bash\npkill -SIGUSR2 -F {}\n".format(DAEMON_PID_FILE))
    TOGGLE_SCRIPT.chmod(0o755)
    CYCLE_SCRIPT.chmod(0o755)

def remove_shortcut_scripts():
    for f in (TOGGLE_SCRIPT, CYCLE_SCRIPT):
        if f.exists():
            f.unlink()

def register_shortcuts():
    result = subprocess.run(
        ['gsettings', 'get', 'org.gnome.settings-daemon.plugins.media-keys', 'custom-keybindings'],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    if raw == "[]":
        raw = "[]"
    elif raw.startswith('[') and raw.endswith(']'):
        pass
    else:
        raw = "[]"
    try:
        current = json.loads(raw)
    except:
        current = []
    toggle_path = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/toggle_dofus/'
    cycle_path  = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/cycle_dofus/'
    if toggle_path not in current:
        current.append(toggle_path)
    if cycle_path not in current:
        current.append(cycle_path)
    subprocess.run([
        'gsettings', 'set',
        'org.gnome.settings-daemon.plugins.media-keys',
        'custom-keybindings', str(current)
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{toggle_path}',
        'name', 'Toggle Dofus Switcher'
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{toggle_path}',
        'command', str(TOGGLE_SCRIPT)
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{toggle_path}',
        'binding', 'F12'
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{cycle_path}',
        'name', 'Cycle Dofus'
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins/media-keys.custom-keybinding:{cycle_path}',
        'command', str(CYCLE_SCRIPT)
    ])
    subprocess.run([
        'gsettings', 'set',
        f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{cycle_path}',
        'binding', 'Tab'
    ])

def unregister_shortcuts():
    result = subprocess.run(
        ['gsettings', 'get', 'org.gnome.settings-daemon.plugins.media-keys', 'custom-keybindings'],
        capture_output=True, text=True
    )
    raw = result.stdout.strip()
    if raw == "[]":
        return
    try:
        current = json.loads(raw)
    except:
        return
    toggle_path = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/toggle_dofus/'
    cycle_path  = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/cycle_dofus/'
    new = [p for p in current if p not in (toggle_path, cycle_path)]
    subprocess.run([
        'gsettings', 'set',
        'org.gnome.settings-daemon.plugins.media-keys',
        'custom-keybindings', str(new)
    ])
    for path in (toggle_path, cycle_path):
        subprocess.run(['gsettings', 'reset', f'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{path}', 'binding'],
                       stderr=subprocess.DEVNULL)

class Switcher:
    def __init__(self):
        self.lock = threading.Lock()
        self.windows = []
        self.current_idx = -1
        self.active = False

    def update_windows(self):
        pids = set()
        try:
            out = subprocess.check_output(['pgrep', '-f', 'Dofus.x64'], text=True, timeout=2)
            pids = set(out.strip().split())
        except:
            pass
        wins = []
        seen_pids = set()
        for pid in pids:
            if pid in seen_pids:
                continue
            try:
                wids = subprocess.check_output(['xdotool', 'search', '--pid', pid], text=True, timeout=2).split()
            except:
                continue
            main_wid = None
            max_area = 0
            for wid in wids:
                try:
                    geo = subprocess.check_output(['xdotool', 'getwindowgeometry', wid], text=True, timeout=1)
                    name = subprocess.check_output(['xdotool', 'getwindowname', wid], text=True, timeout=1).strip()
                except:
                    continue
                w = h = 0
                for line in geo.splitlines():
                    if 'Geometry:' in line:
                        m = re.search(r'(\d+)x(\d+)', line)
                        if m:
                            w, h = int(m.group(1)), int(m.group(2))
                if 'Dofus' in name and w > 100 and h > 100:
                    if w*h > max_area:
                        max_area = w*h
                        main_wid = wid
            if main_wid:
                instance_id = 'unknown'
                try:
                    with open(f'/proc/{pid}/cmdline', 'rb') as f:
                        cmd = f.read().replace(b'\x00', b' ').decode()
                    m = re.search(r'--instanceId\s+(\d+)', cmd)
                    if m:
                        instance_id = m.group(1)
                except:
                    pass
                wins.append({
                    'wid': main_wid,
                    'pid': pid,
                    'instanceId': instance_id,
                    'display_name': f"Instance {instance_id}"
                })
                seen_pids.add(pid)
        wins.sort(key=lambda w: int(w['instanceId']) if w['instanceId'].isdigit() else 0)
        with self.lock:
            self.windows = wins
            if not wins:
                self.current_idx = -1
            elif self.current_idx < 0 or self.current_idx >= len(wins):
                self.current_idx = 0

    def toggle(self):
        with self.lock:
            self.active = not self.active
            state = "ON" if self.active else "OFF"
            print(f"🔀 Switcher {state}", flush=True)

    def next_window(self):
        if not self.active:
            return
        with self.lock:
            if not self.windows:
                return
            self.current_idx = (self.current_idx + 1) % len(self.windows)
            win = self.windows[self.current_idx]
        subprocess.run(['xdotool', 'windowactivate', win['wid']],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"→ {win['display_name']}", flush=True)

switcher = Switcher()

def handle_toggle(sig, frame):
    switcher.toggle()

def handle_next(sig, frame):
    switcher.next_window()

def main():
    DAEMON_PID_FILE.write_text(str(os.getpid()))
    create_shortcut_scripts()
    register_shortcuts()
    atexit.register(lambda: (unregister_shortcuts(), remove_shortcut_scripts(), DAEMON_PID_FILE.unlink(missing_ok=True)))
    switcher.update_windows()
    if not switcher.windows:
        print("❌ No Dofus windows found. Is the game running?", flush=True)
    else:
        print(f"✅ Found {len(switcher.windows)} Dofus windows:", flush=True)
        for i, w in enumerate(switcher.windows):
            print(f"  {i+1}. {w['display_name']} (PID {w['pid']})", flush=True)
    print("🔀 F12 = toggle, TAB = cycle", flush=True)
    print("   (Daemon running – keep this terminal open)", flush=True)
    def refresh():
        while True:
            time.sleep(2)
            switcher.update_windows()
    threading.Thread(target=refresh, daemon=True).start()
    signal.signal(signal.SIGUSR1, handle_toggle)
    signal.signal(signal.SIGUSR2, handle_next)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Cleaning up shortcuts and exiting…")

if __name__ == "__main__":
    main()