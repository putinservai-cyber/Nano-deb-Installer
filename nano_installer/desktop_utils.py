import subprocess
import time
from pathlib import Path

def create_desktop_shortcut(pkg_name: str, log_callback):
    """
    High-level function to create a desktop shortcut for an installed package.
    :param pkg_name: The name of the package.
    :param log_callback: A function to call for logging output (e.g., text_widget.append).
    """
    log_callback(f"\n--- Creating desktop shortcut for {pkg_name} ---")
    try:
        # 1. Find the original .desktop file installed by the package
        dpkg_cmd = ["dpkg", "-L", pkg_name]
        dpkg_proc = subprocess.Popen(dpkg_cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        grep_cmd = ["grep", r'/usr/share/applications/.*\.desktop$']
        grep_proc = subprocess.Popen(grep_cmd, stdin=dpkg_proc.stdout, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        dpkg_proc.stdout.close()
        desktop_files_output, _ = grep_proc.communicate()

        if not desktop_files_output:
            log_callback("[WARNING] No .desktop file found for this package. Creating generic shortcut.")
            _create_generic_shortcut(pkg_name, log_callback)
            return

        desktop_files = [f.strip() for f in desktop_files_output.strip().split('\n') if f.strip()]
        created_shortcuts = []
        
        for desktop_file_path in desktop_files:
            original_desktop_path = Path(desktop_file_path)
            if not original_desktop_path.is_file():
                log_callback(f"[WARNING] Desktop file '{original_desktop_path}' not found, skipping.")
                continue

            log_callback(f"[INFO] Processing: {original_desktop_path}")

            desktop_info = _parse_complete_desktop_file(original_desktop_path)
            if not desktop_info.get("Name") or not desktop_info.get("Exec"):
                log_callback(f"[WARNING] Essential fields missing in {original_desktop_path}, skipping.")
                continue

            if desktop_info.get("NoDisplay", "").lower() == "true":
                log_callback(f"[INFO] Skipping {desktop_info['Name']} (NoDisplay=true)")
                continue

            shortcut_path = _create_enhanced_shortcut(desktop_info, pkg_name, log_callback)
            if shortcut_path:
                created_shortcuts.append(shortcut_path)
                log_callback(f"[SUCCESS] Created shortcut: {shortcut_path}")

        if created_shortcuts:
            log_callback(f"[SUCCESS] Created {len(created_shortcuts)} desktop shortcut(s)")
            _refresh_desktop(log_callback)
        else:
            log_callback("[WARNING] No valid shortcuts could be created")
            
    except Exception as e:
        log_callback(f"[ERROR] Failed to create desktop shortcut: {e}")

def remove_desktop_shortcuts(pkg_name: str, log_callback):
    """
    High-level function to find and remove all desktop shortcuts for a package.
    :param pkg_name: The name of the package to remove shortcuts for.
    :param log_callback: A function to call for logging output.
    """
    log_callback("\n--- Removing desktop shortcuts ---")
    shortcuts_to_remove = _find_shortcuts_for_removal(pkg_name, log_callback)
    
    if not shortcuts_to_remove:
        log_callback("[INFO] No desktop shortcuts found for this package.")
        return

    removed_count = 0
    failed_count = 0
    
    for shortcut_path in shortcuts_to_remove:
        try:
            if shortcut_path.is_file():
                shortcut_path.unlink()
                log_callback(f"[SUCCESS] Removed: {shortcut_path.name}")
                removed_count += 1
            else:
                log_callback(f"[INFO] Not found: {shortcut_path.name}")
        except Exception as e:
            log_callback(f"[ERROR] Failed to remove {shortcut_path.name}: {e}")
            failed_count += 1
    
    if removed_count > 0:
        log_callback(f"[SUCCESS] Removed {removed_count} desktop shortcut(s)")
    if failed_count > 0:
        log_callback(f"[WARNING] Failed to remove {failed_count} shortcut(s)")
        
    _refresh_desktop(log_callback)


def _find_shortcuts_for_removal(pkg_name: str, log_callback) -> list[Path]:
    """Finds all potential desktop shortcuts associated with a package."""
    shortcuts_to_remove = []
    log_callback("--- Checking for desktop shortcuts to remove ---")
    
    desktop_dir = _get_desktop_directory(log_callback)
    if not desktop_dir:
        log_callback("[INFO] No Desktop directory found. Skipping shortcut removal.")
        return []

    found_paths = set()

    # Methods to find shortcuts, adding to a set to avoid duplicates
    _find_shortcuts_from_installed_files(pkg_name, desktop_dir, found_paths)
    _find_shortcuts_by_metadata(pkg_name, desktop_dir, found_paths)
    _find_shortcuts_by_package_name(pkg_name, desktop_dir, found_paths)
    
    shortcuts_to_remove = list(found_paths)
    if shortcuts_to_remove:
        log_callback(f"[INFO] Found {len(shortcuts_to_remove)} shortcut(s) to remove")
        for shortcut in shortcuts_to_remove:
            log_callback(f"[INFO] Will remove: {shortcut}")
    
    return shortcuts_to_remove


# --- Internal Helper Functions ---

def _parse_complete_desktop_file(file_path: Path) -> dict:
    config = {}
    if not file_path.is_file(): return config
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            in_desktop_entry = False
            for line in f:
                line = line.strip()
                if line == '[Desktop Entry]':
                    in_desktop_entry = True
                    continue
                if not in_desktop_entry or not line or line.startswith('#') or '=' not in line:
                    continue
                if line.startswith('[') and line.endswith(']'): break
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    except IOError:
        return {}
    return config

def _create_enhanced_shortcut(desktop_info: dict, pkg_name: str, log_callback) -> Path | None:
    desktop_dir = _get_desktop_directory(log_callback)
    if not desktop_dir: return None
    
    app_name = desktop_info.get('Name', 'Unknown App')
    safe_filename = _create_safe_filename(app_name)
    shortcut_path = desktop_dir / f"{safe_filename}.desktop"
    
    counter = 1
    while shortcut_path.exists():
        shortcut_path = desktop_dir / f"{safe_filename}_{counter}.desktop"
        counter += 1
    
    content = _build_desktop_file_content(desktop_info, pkg_name)
    
    try:
        shortcut_path.write_text(content, encoding='utf-8')
        shortcut_path.chmod(0o755)
        _mark_shortcut_trusted(shortcut_path, log_callback)
        return shortcut_path
    except Exception as e:
        log_callback(f"[ERROR] Failed to write shortcut file: {e}")
        return None

def _get_desktop_directory(log_callback) -> Path | None:
    try:
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, check=True)
        desktop_path = Path(result.stdout.strip())
        if desktop_path.is_dir(): return desktop_path
    except (subprocess.CalledProcessError, FileNotFoundError): pass
    
    for desktop_name in ['Desktop', 'Рабочий стол', 'デスクトップ', 'Bureau', 'Escritorio']:
        desktop_path = Path.home() / desktop_name
        if desktop_path.is_dir(): return desktop_path
    
    desktop_path = Path.home() / 'Desktop'
    try:
        desktop_path.mkdir(exist_ok=True)
        return desktop_path
    except Exception as e:
        log_callback(f"[ERROR] Cannot create Desktop directory: {e}")
        return None

def _create_safe_filename(name: str) -> str:
    safe_chars = [c if c.isalnum() or c in ' -_.' else '_' for c in name]
    safe_name = ''.join(safe_chars).strip()
    safe_name = ' '.join(safe_name.split())
    safe_name = safe_name.replace(' ', '_')
    return safe_name[:50]

def _build_desktop_file_content(desktop_info: dict, pkg_name: str) -> str:
    content = "[Desktop Entry]\n"
    content += f"Version={desktop_info.get('Version', '1.0')}\n"
    content += f"Type={desktop_info.get('Type', 'Application')}\n"
    content += f"Name={desktop_info['Name']}\n"
    if desktop_info.get('GenericName'): content += f"GenericName={desktop_info['GenericName']}\n"
    if desktop_info.get('Comment'): content += f"Comment={desktop_info['Comment']}\n"
    content += f"Exec={desktop_info['Exec']}\n"
    if desktop_info.get('Path'): content += f"Path={desktop_info['Path']}\n"
    content += f"Terminal={desktop_info.get('Terminal', 'false')}\n"
    if desktop_info.get('Icon'): content += f"Icon={desktop_info['Icon']}\n"
    content += f"Categories={desktop_info.get('Categories', 'Application;')}\n"
    if desktop_info.get('Keywords'): content += f"Keywords={desktop_info['Keywords']}\n"
    if desktop_info.get('MimeType'): content += f"MimeType={desktop_info['MimeType']}\n"
    content += f"StartupNotify={desktop_info.get('StartupNotify', 'true')}\n"
    if desktop_info.get('StartupWMClass'): content += f"StartupWMClass={desktop_info['StartupWMClass']}\n"
    
    content += _add_kde_actions(desktop_info, pkg_name)
    
    content += "X-Created-By=Nano Installer\n"
    content += f"X-Creation-Time={int(time.time())}\n"
    content += "X-Plasma-Trusted=true\n"
    return content

def _add_kde_actions(desktop_info: dict, pkg_name: str) -> str:
    actions_content = "Actions=Settings;About;Uninstall;\n\n"
    app_name = desktop_info.get('Name', 'Application')
    exec_cmd = desktop_info.get('Exec', '')
    base_cmd = exec_cmd.split()[0] if exec_cmd else ''

    # Settings action
    actions_content += "[Desktop Action Settings]\n"
    actions_content += f"Name=Configure {app_name}\n"
    actions_content += "Icon=configure\n"
    settings_cmd = f"{base_cmd} --preferences" if base_cmd else "systemsettings5"
    actions_content += f"Exec={settings_cmd}\n\n"
    
    # About action
    actions_content += "[Desktop Action About]\n"
    actions_content += f"Name=About {app_name}\n"
    actions_content += "Icon=help-about\n"
    about_cmd = f"{base_cmd} --help" if base_cmd else "khelpcenter"
    actions_content += f"Exec={about_cmd}\n\n"
    
    # Uninstall action
    actions_content += "[Desktop Action Uninstall]\n"
    actions_content += f"Name=Uninstall {app_name}\n"
    actions_content += "Icon=edit-delete\n"
    installer_path = str(Path(__file__).parent.parent / "main.py")
    actions_content += f"Exec=python3 '{installer_path}' --uninstall '{pkg_name}'\n\n"
    
    return actions_content

def _mark_shortcut_trusted(shortcut_path: Path, log_callback):
    try:
        # Use kwriteconfig5 for KDE configuration
        subprocess.run(['kwriteconfig5', '--file', str(shortcut_path), '--group', 'Desktop Entry', '--key', 'X-Plasma-Trusted', 'true'], capture_output=True, timeout=5)
        # Set executable permissions
        shortcut_path.chmod(shortcut_path.stat().st_mode | 0o111)
    except Exception as e:
        log_callback(f"[INFO] Could not run KDE-specific trust commands: {e}")

def _refresh_desktop(log_callback):
    log_callback("[INFO] Refreshing desktop to show new shortcuts...")
    commands = [
        ['kbuildsycoca5', '--noincremental'],
        ['update-desktop-database', str(Path.home() / '.local/share/applications')],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode == 0:
                log_callback(f"[SUCCESS] Desktop refresh: {' '.join(cmd)}")
                break
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue

def _create_generic_shortcut(pkg_name: str, log_callback):
    try:
        desktop_dir = _get_desktop_directory(log_callback)
        if not desktop_dir: return
        
        safe_filename = _create_safe_filename(pkg_name)
        shortcut_path = desktop_dir / f"{safe_filename}.desktop"
        
        description = "Installed application"
        try:
            desc_result = subprocess.run(['apt-cache', 'show', pkg_name], capture_output=True, text=True)
            for line in desc_result.stdout.split('\n'):
                if line.startswith('Description:'):
                    description = line.split(':', 1)[1].strip()
                    break
        except Exception: pass
        
        content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={pkg_name.title()}
Comment={description}
Icon=application-x-executable
Exec={pkg_name}
Terminal=false
Categories=Application;
StartupNotify=true
X-Created-By=Nano Installer
X-Creation-Time={int(time.time())}
"""
        shortcut_path.write_text(content, encoding='utf-8')
        shortcut_path.chmod(0o755)
        log_callback(f"[SUCCESS] Created generic shortcut: {shortcut_path}")
    except Exception as e:
        log_callback(f"[ERROR] Failed to create generic shortcut: {e}")


# --- Removal Helpers ---

def _find_shortcuts_from_installed_files(pkg_name: str, desktop_dir: Path, found_paths: set):
    try:
        dpkg_cmd = ["dpkg", "-L", pkg_name]
        dpkg_proc = subprocess.Popen(dpkg_cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        grep_cmd = ["grep", r'/usr/share/applications/.*\.desktop$']
        grep_proc = subprocess.Popen(grep_cmd, stdin=dpkg_proc.stdout, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        dpkg_proc.stdout.close()
        desktop_files_output, _ = grep_proc.communicate()
        
        if not desktop_files_output: return
        
        for desktop_file_path in desktop_files_output.strip().split('\n'):
            original_desktop_path = Path(desktop_file_path.strip())
            if not original_desktop_path.is_file(): continue
            
            desktop_info = _parse_complete_desktop_file(original_desktop_path)
            app_name = desktop_info.get("Name")
            if not app_name: continue
            
            safe_filename = _create_safe_filename(app_name)
            for i in range(5): # Check for numbered files like _1, _2 etc.
                name_to_check = f"{safe_filename}.desktop" if i == 0 else f"{safe_filename}_{i}.desktop"
                shortcut_path = desktop_dir / name_to_check
                if shortcut_path.is_file():
                    found_paths.add(shortcut_path)
    except Exception: pass

def _find_shortcuts_by_metadata(pkg_name: str, desktop_dir: Path, found_paths: set):
    try:
        for shortcut_file in desktop_dir.glob("*.desktop"):
            try:
                content = shortcut_file.read_text(encoding='utf-8')
                is_our_shortcut = "X-Created-By=Nano Installer" in content
                uninstall_action_correct = f"--uninstall '{pkg_name}'" in content
                if is_our_shortcut and uninstall_action_correct:
                    found_paths.add(shortcut_file)
            except Exception: continue
    except Exception: pass

def _find_shortcuts_by_package_name(pkg_name: str, desktop_dir: Path, found_paths: set):
    try:
        safe_pkg_name = _create_safe_filename(pkg_name)
        for name in [f"{safe_pkg_name}.desktop", f"{pkg_name}.desktop"]:
            shortcut_path = desktop_dir / name
            if shortcut_path.is_file():
                found_paths.add(shortcut_path)
    except Exception: pass