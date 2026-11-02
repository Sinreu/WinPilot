"""Windows maintenance operations. No privileged or hidden automatic tweaks."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

IS_WINDOWS = os.name == 'nt'
if IS_WINDOWS:
    import winreg
else:
    winreg = None

APP_DIR = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.local' / 'share')) / 'WinPilot'
STATE_FILE = APP_DIR / 'state.json'


def ensure_windows() -> None:
    if not IS_WINDOWS:
        raise RuntimeError('WinPilot работает только в Windows.')


def _default_state() -> dict:
    return {'version': 1, 'disabled_startup': {}, 'tweak_backups': {}, 'power_backup': None}


def load_state() -> dict:
    if not STATE_FILE.is_file():
        return _default_state()
    with STATE_FILE.open('r', encoding='utf-8') as f:
        state = json.load(f)
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError('Неподдерживаемый формат state.json')
    for k, value in _default_state().items():
        state.setdefault(k, value)
    return state


def save_state(state: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='state-', suffix='.tmp', dir=APP_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, STATE_FILE)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _is_reparse(path: Path) -> bool:
    """Avoid following junctions and symlinks in temporary directories."""
    try:
        if path.is_symlink():
            return True
        st = path.lstat()
        return bool(getattr(st, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(root.resolve()), str(path.resolve()))) == str(root.resolve())
    except (OSError, ValueError):
        return False


@dataclass
class CleanupSummary:
    files: int
    bytes: int
    skipped: int = 0


def _temp_root() -> Path:
    ensure_windows()
    return Path(tempfile.gettempdir()).resolve()


def scan_temp(root: Optional[Path] = None, *, hours: int = 24) -> tuple[list[Path], CleanupSummary]:
    """List old regular files under user temp; never enter symlinks/junctions.

    The root is a user-specific temporary directory; this intentionally does not
    scan Downloads, Prefetch, system-wide Windows folders or browser profiles.
    """
    root = (Path(root) if root is not None else _temp_root()).resolve()
    if root.is_symlink() or _is_reparse(root) or not root.is_dir():
        raise ValueError('Недоступная или небезопасная папка временных файлов.')
    cutoff = time.time() - hours * 3600
    candidates: list[Path] = []
    size = 0
    skipped = 0
    for dirpath, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        dirs[:] = [d for d in dirs if not _is_reparse(current / d)]
        for name in files:
            p = current / name
            try:
                if _is_reparse(p) or not _is_within(p, root):
                    skipped += 1
                    continue
                st = p.stat()
                if p.is_file() and st.st_mtime < cutoff:
                    candidates.append(p)
                    size += st.st_size
            except (PermissionError, FileNotFoundError, OSError):
                skipped += 1
    return candidates, CleanupSummary(len(candidates), size, skipped)


def clean_temp(root: Optional[Path] = None, *, hours: int = 24) -> CleanupSummary:
    """Rescan before deletion, with another mtime/type check for every file."""
    files, scanned = scan_temp(root, hours=hours)
    base = (Path(root) if root is not None else _temp_root()).resolve()
    deleted = 0
    size = 0
    skipped = scanned.skipped
    cutoff = time.time() - hours * 3600
    for path in files:
        try:
            # Check each path component is not reparse-point before unlink.
            cur = path.parent
            valid = True
            while cur != base:
                if _is_reparse(cur) or not _is_within(cur, base):
                    valid = False
                    break
                if cur == cur.parent:
                    valid = False
                    break
                cur = cur.parent
            if not valid or _is_reparse(path) or not _is_within(path, base):
                skipped += 1
                continue
            st = path.stat()
            if not path.is_file() or st.st_mtime >= cutoff:
                skipped += 1
                continue
            path.unlink()
            size += st.st_size
            deleted += 1
        except (PermissionError, FileNotFoundError, IsADirectoryError, OSError):
            skipped += 1
    # Deliberately leave directories in place to avoid deleting active app folders.
    return CleanupSummary(deleted, size, skipped)


def format_size(n: int) -> str:
    value = float(max(0, n))
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if value < 1024 or unit == 'ТБ':
            return f'{value:.1f} {unit}' if unit != 'Б' else f'{int(value)} Б'
        value /= 1024
    return '0 Б'


REG_RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _query_reg(hive: Any, subkey: str, name: str) -> tuple[bool, Any, Optional[int]]:
    ensure_windows()
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
            value, regtype = winreg.QueryValueEx(key, name)
            return True, value, regtype
    except FileNotFoundError:
        return False, None, None


def _write_reg(hive: Any, subkey: str, name: str, value: Any, regtype: int) -> None:
    ensure_windows()
    with winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, regtype, value)


def _delete_reg(hive: Any, subkey: str, name: str) -> None:
    ensure_windows()
    with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, name)


def list_startup() -> list[dict]:
    ensure_windows()
    entries = []
    state = load_state()
    for scope, hive in [('HKCU', winreg.HKEY_CURRENT_USER), ('HKLM', winreg.HKEY_LOCAL_MACHINE)]:
        try:
            with winreg.OpenKey(hive, REG_RUN, 0, winreg.KEY_READ) as key:
                count = winreg.QueryInfoKey(key)[1]
                for i in range(count):
                    name, value, kind = winreg.EnumValue(key, i)
                    entries.append({'id': f'active|{scope}|{name}', 'name': name, 'command': str(value),
                                    'scope': scope, 'status': 'Включена', 'type': kind})
        except (OSError, PermissionError):
            pass
    for name, entry in state['disabled_startup'].items():
        entries.append({'id': f'disabled|{name}', 'name': name, 'command': entry['value'],
                        'scope': 'HKCU', 'status': 'Отключена (WinPilot)', 'type': entry['type']})
    return sorted(entries, key=lambda e: (e['scope'], e['name'].casefold(), e['status']))


def disable_startup(name: str) -> None:
    ensure_windows()
    state = load_state()
    if name in state['disabled_startup']:
        raise ValueError('Запись уже отключена.')
    exists, value, kind = _query_reg(winreg.HKEY_CURRENT_USER, REG_RUN, name)
    if not exists or kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        raise ValueError('Не найдена поддерживаемая запись в автозагрузке пользователя.')
    # Save backup BEFORE removing from registry to prevent data loss.
    state['disabled_startup'][name] = {'value': value, 'type': kind}
    save_state(state)
    _delete_reg(winreg.HKEY_CURRENT_USER, REG_RUN, name)


def restore_startup(name: str) -> None:
    ensure_windows()
    state = load_state()
    record = state['disabled_startup'].get(name)
    if record is None:
        raise ValueError('Резервная копия записи не найдена.')
    exists, _, _ = _query_reg(winreg.HKEY_CURRENT_USER, REG_RUN, name)
    if exists:
        raise ValueError('Такая запись уже существует. Откат остановлен, чтобы ничего не перезаписать.')
    _write_reg(winreg.HKEY_CURRENT_USER, REG_RUN, name, record['value'], record['type'])
    del state['disabled_startup'][name]
    save_state(state)


@dataclass(frozen=True)
class Tweak:
    id: str
    label: str
    description: str
    subkey: str
    name: str
    optimized: Any
    reg_type: int


def tweaks() -> list[Tweak]:
    ensure_windows()
    return [
        Tweak('animations', 'Уменьшить анимации окон',
              'Отключает сворачивание/разворачивание с анимацией. Не увеличивает FPS в играх.',
              r'Control Panel\Desktop\WindowMetrics', 'MinAnimate', '0', winreg.REG_SZ),
        Tweak('transparency', 'Отключить прозрачность интерфейса',
              'Убирает полупрозрачные эффекты Windows, может чуть снизить нагрузку на графику.',
              r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize',
              'EnableTransparency', 0, winreg.REG_DWORD),
        Tweak('game_capture', 'Отключить фоновую запись Game DVR',
              'Отключает захват через Game DVR. Запись клипов Xbox Game Bar может перестать работать.',
              r'System\GameConfigStore', 'GameDVR_Enabled', 0, winreg.REG_DWORD),
    ]


def tweak_status(t: Tweak) -> tuple[bool, bool]:
    ensure_windows()
    exists, value, kind = _query_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name)
    applied = exists and value == t.optimized and kind == t.reg_type
    tracked = t.id in load_state()['tweak_backups']
    return applied, tracked


def apply_tweak(t: Tweak) -> None:
    ensure_windows()
    state = load_state()
    if t.id not in state['tweak_backups']:
        exists, val, kind = _query_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name)
        if kind not in (winreg.REG_SZ, winreg.REG_DWORD, None):
            raise ValueError('Неподдерживаемый тип существующего параметра, изменение отменено.')
        state['tweak_backups'][t.id] = {'exists': exists, 'value': val, 'type': kind}
        save_state(state)
    _write_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name, t.optimized, t.reg_type)


def restore_tweak(t: Tweak) -> None:
    ensure_windows()
    state = load_state()
    backup = state['tweak_backups'].get(t.id)
    if backup is None:
        raise ValueError('WinPilot не менял этот параметр, откат недоступен.')
    exists, value, kind = _query_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name)
    if not exists or value != t.optimized or kind != t.reg_type:
        raise ValueError('Параметр изменён другой программой. Откат остановлен.')
    if backup['exists']:
        _write_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name, backup['value'], backup['type'])
    else:
        _delete_reg(winreg.HKEY_CURRENT_USER, t.subkey, t.name)
    del state['tweak_backups'][t.id]
    save_state(state)


POWER_GUID = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}')


def _run(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess:
    ensure_windows()
    return subprocess.run(args, capture_output=True, text=True, encoding='oem', errors='replace',
                          timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def power_plans() -> tuple[list[tuple[str, str]], Optional[str]]:
    result = _run(['powercfg', '/list'])
    if result.returncode:
        raise RuntimeError(result.stdout + '\n' + result.stderr)
    plans = []
    active = None
    for line in result.stdout.splitlines():
        match = POWER_GUID.search(line)
        if match:
            guid = match.group().lower()
            label = line[match.end():].strip().lstrip('(').rstrip(')').strip()
            # On Windows * marks currently active power plan.
            if '*' in line:
                active = guid
            plans.append((guid, label.replace('*', '').strip() or guid))
    return plans, active


def set_power_plan(guid: str) -> None:
    ensure_windows()
    if not POWER_GUID.fullmatch(guid):
        raise ValueError('Некорректный GUID схемы питания.')
    plans, active = power_plans()
    if guid not in {p[0] for p in plans}:
        raise ValueError('Выбранная схема питания отсутствует в системе.')
    state = load_state()
    if not state['power_backup'] and active:
        state['power_backup'] = active
        save_state(state)
    result = _run(['powercfg', '/setactive', guid])
    if result.returncode:
        raise RuntimeError(result.stdout + '\n' + result.stderr)


def restore_power_plan() -> None:
    ensure_windows()
    state = load_state()
    previous = state['power_backup']
    if not previous:
        raise ValueError('Нет сохранённой схемы питания.')
    plans, _ = power_plans()
    if previous not in {p[0] for p in plans}:
        raise RuntimeError('Сохранённой схемы больше нет в системе.')
    result = _run(['powercfg', '/setactive', previous])
    if result.returncode:
        raise RuntimeError(result.stdout + '\n' + result.stderr)
    state['power_backup'] = None
    save_state(state)


def system_info() -> dict:
    ensure_windows()
    disk = shutil.disk_usage(os.environ.get('SystemDrive', 'C:') + '\\')
    # GetTickCount64 returns ms since boot, excluding hibernated duration.
    try:
        uptime_seconds = int(ctypes.windll.kernel32.GetTickCount64() / 1000)
    except Exception:
        uptime_seconds = 0
    return {
        'os': platform.platform(), 'hostname': platform.node(),
        'cpu': platform.processor() or 'Не определён',
        'disk_total': disk.total, 'disk_free': disk.free,
        'uptime_hours': round(uptime_seconds / 3600, 1),
        'startup_count': len([e for e in list_startup() if e['status'] == 'Включена']),
    }


def open_windows_startup() -> None:
    ensure_windows()
    os.startfile('ms-settings:startupapps')


def flush_dns() -> str:
    result = _run(['ipconfig', '/flushdns'], timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + '\n' + result.stderr)
    return result.stdout.strip() or 'Кэш DNS очищен.'


def log_line(message: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with (APP_DIR / 'operations.log').open('a', encoding='utf-8') as f:
        f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n')
