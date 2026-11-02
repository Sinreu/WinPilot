"""WinPilot graphical UI, Tkinter / ttk; no third-party runtime dependencies."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from . import core

BG = '#0c111b'
PANEL = '#151e2d'
PANEL_2 = '#1a2638'
EDGE = '#2a394d'
FG = '#e9f1ff'
MUTED = '#95a8c3'
ACCENT = '#67aaff'
GOOD = '#7de6b4'
WARN = '#f0c674'


class WinPilotApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title('WinPilot — безопасный оптимизатор Windows')
        self.root.geometry('1120x730')
        self.root.minsize(930, 620)
        self.root.configure(bg=BG)
        self.jobs: queue.Queue = queue.Queue()
        self.working = False
        self.temp_summary = None
        self._set_style()
        self.shell = tk.Frame(self.root, bg=BG)
        self.shell.pack(fill='both', expand=True)
        self.sidebar = tk.Frame(self.shell, bg=PANEL, width=220)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(self.shell, bg=BG)
        self.main.pack(side='left', fill='both', expand=True)
        self.status_var = tk.StringVar(value='Готово к работе. Изменения не применяются автоматически.')
        self.status_bar = tk.Label(self.root, textvariable=self.status_var, bg=PANEL_2,
                                   fg=MUTED, anchor='w', padx=18, pady=9, font=('Segoe UI', 9))
        self.status_bar.pack(fill='x', side='bottom')
        self.menu_buttons = {}
        self.current_page = ''
        self._make_menu()
        self.show_page('overview')
        self.root.after(120, self._poll)

    def _set_style(self) -> None:
        s = ttk.Style()
        s.theme_use('clam')
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=34, bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE,
                    font=('Segoe UI', 10))
        s.map('Treeview', background=[('selected', '#264d78')], foreground=[('selected', '#ffffff')])
        s.configure('Treeview.Heading', background=PANEL_2, foreground=FG,
                    font=('Segoe UI Semibold', 10), relief='flat', padding=8)
        s.map('Treeview.Heading', background=[('active', '#28405a')])
        s.configure('TScrollbar', troughcolor=BG, background=PANEL_2,
                    arrowcolor=FG, bordercolor=PANEL, lightcolor=PANEL_2, darkcolor=PANEL_2)
        s.configure('TCombobox', foreground=FG, fieldbackground=PANEL_2, background=PANEL_2,
                    arrowcolor=FG, selectbackground=PANEL_2, selectforeground=FG)
        s.map('TCombobox', fieldbackground=[('readonly', PANEL_2)],
              foreground=[('readonly', FG)])

    def _label(self, parent, txt, size=11, color=FG, bold=False, **kw):
        # Allow callers to override Tk options without duplicate keywords.
        return tk.Label(parent, text=txt, bg=kw.pop('bg', BG), fg=color,
                        font=('Segoe UI Semibold' if bold else 'Segoe UI', size),
                        justify=kw.pop('justify', 'left'), anchor=kw.pop('anchor', 'w'), **kw)

    def _button(self, parent, text, action, primary=False, **kw):
        bg = ACCENT if primary else PANEL_2
        fg = '#101b29' if primary else FG
        b = tk.Button(parent, text=text, command=action, bg=bg, fg=fg,
                      activebackground='#91c2ff' if primary else '#2c4260',
                      activeforeground='#101b29' if primary else 'white',
                      relief='flat', borderwidth=0, cursor='hand2',
                      font=('Segoe UI Semibold', 10), padx=18, pady=10, **kw)
        return b

    def _card(self, parent, **kw):
        return tk.Frame(parent, bg=PANEL, highlightbackground=EDGE,
                        highlightthickness=1, **kw)

    def _make_menu(self) -> None:
        header = tk.Frame(self.sidebar, bg=PANEL)
        header.pack(fill='x', padx=21, pady=(28, 26))
        self._label(header, '◈  WinPilot', 20, FG, True, bg=PANEL).pack(anchor='w')
        self._label(header, 'WINDOWS CONTROL CENTER', 8, MUTED, bg=PANEL).pack(anchor='w', pady=(3, 0))
        pages = [
            ('overview', '◫  Обзор'),
            ('cleanup', '◈  Очистка'),
            ('startup', '▣  Автозагрузка'),
            ('tweaks', '◇  Настройки'),
            ('diagnostics', '◉  Диагностика'),
            ('logs', '≡  Журнал'),
        ]
        for key, text in pages:
            b = tk.Button(self.sidebar, text=text, bg=PANEL, fg=MUTED,
                          activebackground=PANEL_2, activeforeground=FG,
                          font=('Segoe UI', 11), anchor='w', relief='flat',
                          padx=20, pady=14, borderwidth=0, cursor='hand2',
                          command=lambda k=key: self.show_page(k))
            b.pack(fill='x', padx=9, pady=2)
            self.menu_buttons[key] = b
        self._label(self.sidebar, 'v1.0.1  •  Без телеметрии', 9, MUTED,
                    bg=PANEL).pack(side='bottom', anchor='w', padx=19, pady=24)

    def _heading(self, parent, title, desc) -> None:
        self._label(parent, title, 24, FG, True).pack(anchor='w', pady=(0, 5))
        self._label(parent, desc, 10, MUTED, wraplength=790).pack(anchor='w', pady=(0, 24))

    def show_page(self, key: str) -> None:
        self.current_page = key
        for name, b in self.menu_buttons.items():
            b.configure(bg=PANEL_2 if name == key else PANEL,
                        fg=FG if name == key else MUTED)
        for child in self.main.winfo_children():
            child.destroy()
        body = tk.Frame(self.main, bg=BG)
        body.pack(fill='both', expand=True, padx=32, pady=28)
        getattr(self, f'_page_{key}')(body)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _task(self, description: str, action: Callable, done: Callable | None = None) -> None:
        if self.working:
            messagebox.showinfo('WinPilot', 'Другая операция уже выполняется.')
            return
        self.working = True
        self._set_status(f'Выполняется: {description}…')

        def work():
            try:
                result = action()
                self.jobs.put((description, result, None, done))
            except Exception as exc:
                self.jobs.put((description, None, str(exc), done))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                description, result, err, done = self.jobs.get_nowait()
                self.working = False
                if err:
                    core.log_line(f'ОШИБКА: {description} — {err}')
                    self._set_status(f'Ошибка: {description}')
                    messagebox.showerror('WinPilot', err)
                else:
                    core.log_line(f'УСПЕХ: {description}')
                    self._set_status(f'Готово: {description}')
                    if done:
                        done(result)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _page_overview(self, body) -> None:
        self._heading(body, 'Состояние компьютера',
                      'Контроль Windows без рискованных «твиков» и выдуманных ускорений.')
        top = tk.Frame(body, bg=BG)
        top.pack(fill='x')
        cards = [('ОС', 'Windows', 'Изменения только по вашему выбору'),
                 ('Система', 'Диагностика', 'Диск, автозагрузка и время работы'),
                 ('Безопасность', 'Контроль', 'Резервные копии изменённых настроек')]
        for i, (title, value, sub) in enumerate(cards):
            card = self._card(top)
            card.grid(row=0, column=i, padx=(0, 12) if i < 2 else 0, sticky='nsew')
            top.columnconfigure(i, weight=1)
            self._label(card, title, 10, MUTED, bg=PANEL).pack(anchor='w', padx=19, pady=(17, 6))
            self._label(card, value, 19, FG, True, bg=PANEL).pack(anchor='w', padx=19)
            self._label(card, sub, 9, MUTED, bg=PANEL, wraplength=200).pack(anchor='w', padx=19, pady=(5, 19))
        detail = self._card(body)
        detail.pack(fill='x', pady=(21, 0))
        self._label(detail, 'Сведения о системе', 14, FG, True, bg=PANEL).pack(anchor='w', padx=20, pady=(20, 10))
        info_label = self._label(detail, 'Загрузка данных…', 11, FG, bg=PANEL, justify='left')
        info_label.pack(anchor='w', padx=20, pady=(0, 20))

        def update(data):
            if info_label.winfo_exists():
                info_label.configure(text=(f"Компьютер: {data['hostname']}\n"
                    f"Система: {data['os']}\n"
                    f"Свободно на системном диске: {core.format_size(data['disk_free'])} "
                    f"из {core.format_size(data['disk_total'])}\n"
                    f"Время работы: {data['uptime_hours']} ч\n"
                    f"Записей в автозагрузке: {data['startup_count']}"))
        self._task('Сбор сведений о системе', core.system_info, update)
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill='x', pady=(22, 0))
        self._button(actions, 'Проверить временные файлы',
                     lambda: self.show_page('cleanup'), primary=True).pack(side='left', padx=(0, 12))
        self._button(actions, 'Управлять автозагрузкой',
                     lambda: self.show_page('startup')).pack(side='left')

    def _page_cleanup(self, body) -> None:
        self._heading(body, 'Очистка временных файлов',
                      'Только пользовательская папка TEMP. Файлы моложе 24 часов не затрагиваются; занятые файлы пропускаются.')
        card = self._card(body)
        card.pack(fill='x')
        self._label(card, 'Предварительный анализ', 14, FG, True, bg=PANEL).pack(anchor='w', padx=22, pady=(22, 6))
        self._label(card, 'Удаление производится только после отдельного подтверждения.',
                    10, MUTED, bg=PANEL).pack(anchor='w', padx=22)
        self.cleanup_info = self._label(card, 'Нажмите «Сканировать» для подсчёта файлов.',
                                        13, FG, True, bg=PANEL)
        self.cleanup_info.pack(anchor='w', padx=22, pady=(25, 17))
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(anchor='w', padx=22, pady=(0, 22))
        self._button(buttons, 'Сканировать', self._scan_temp, primary=True).pack(side='left', padx=(0, 10))
        self.clean_button = self._button(buttons, 'Очистить найденное', self._confirm_clean)
        self.clean_button.pack(side='left')
        self.clean_button.configure(state='disabled')
        note = self._card(body)
        note.pack(fill='x', pady=(20, 0))
        self._label(note, 'Что программа НЕ удаляет', 12, FG, True, bg=PANEL).pack(anchor='w', padx=21, pady=(19, 6))
        self._label(note,
                    'Загрузки, документы, игровые сохранения, Prefetch, системные папки Windows, '
                    'браузерные профили и файлы с недавними изменениями.',
                    10, MUTED, bg=PANEL, wraplength=700).pack(anchor='w', padx=21, pady=(0, 19))

    def _scan_temp(self) -> None:
        def done(data):
            _, summary = data
            self.temp_summary = summary
            if self.current_page == 'cleanup':
                self.cleanup_info.configure(text=f'{summary.files} файлов  •  {core.format_size(summary.bytes)} '
                                                 f'•  пропущено: {summary.skipped}')
                self.clean_button.configure(state='normal' if summary.files else 'disabled')
        self._task('Анализ временных файлов', core.scan_temp, done)

    def _confirm_clean(self) -> None:
        if not self.temp_summary:
            return
        if not messagebox.askyesno('Подтверждение очистки',
                f'Удалить старые файлы из пользовательской TEMP?\n\n'
                f'Предварительно: {self.temp_summary.files} файлов, '
                f'{core.format_size(self.temp_summary.bytes)}.\n\n'
                'Это не перемещение в корзину, отменить очистку нельзя.'):
            return
        def done(summary):
            if self.current_page == 'cleanup':
                self.cleanup_info.configure(text=f'Удалено {summary.files} файлов '
                                                 f'({core.format_size(summary.bytes)}), '
                                                 f'пропущено: {summary.skipped}')
                self.clean_button.configure(state='disabled')
            messagebox.showinfo('Очистка завершена',
                                f'Удалено: {summary.files} файлов, {core.format_size(summary.bytes)}.\n'
                                f'Пропущено: {summary.skipped}.')
        self._task('Очистка старых временных файлов', core.clean_temp, done)

    def _page_startup(self, body) -> None:
        self._heading(body, 'Управление автозагрузкой',
                      'Записи пользователя HKCU можно отключить и вернуть. Системные записи HKLM — только просмотр.')
        tablebox = self._card(body)
        tablebox.pack(fill='both', expand=True)
        cols = ('name', 'command', 'scope', 'status')
        self.startup_tree = ttk.Treeview(tablebox, columns=cols, show='headings', selectmode='browse')
        for c, text, width in [('name','Название',175), ('command','Команда запуска',300),
                               ('scope','Раздел',75), ('status','Состояние',170)]:
            self.startup_tree.heading(c, text=text)
            self.startup_tree.column(c, width=width, minwidth=60, stretch=(c == 'command'))
        scr = ttk.Scrollbar(tablebox, orient='vertical', command=self.startup_tree.yview)
        self.startup_tree.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y', pady=12)
        self.startup_tree.pack(fill='both', expand=True, padx=(12, 0), pady=12)
        bottom = tk.Frame(body, bg=BG)
        bottom.pack(fill='x', pady=(16, 0))
        self._button(bottom, 'Обновить', self._refresh_startup, primary=True).pack(side='left', padx=(0, 10))
        self._button(bottom, 'Отключить выбранную', self._disable_selected).pack(side='left', padx=(0, 10))
        self._button(bottom, 'Восстановить выбранную', self._restore_selected).pack(side='left', padx=(0, 10))
        self._button(bottom, 'Настройки Windows', self._open_startup_settings).pack(side='right')
        self._refresh_startup()

    def _refresh_startup(self):
        def done(entries):
            if self.current_page != 'startup':
                return
            self.startup_tree.delete(*self.startup_tree.get_children())
            for e in entries:
                self.startup_tree.insert('', 'end', iid=e['id'],
                                         values=(e['name'], e['command'], e['scope'], e['status']))
        self._task('Чтение автозагрузки', core.list_startup, done)

    def _selected_startup(self):
        sel = self.startup_tree.selection()
        if not sel:
            messagebox.showinfo('Выбор', 'Сначала выберите запись в таблице.')
            return None
        parts = sel[0].split('|', 2)
        return parts

    def _disable_selected(self):
        parts = self._selected_startup()
        if not parts:
            return
        if parts[0] != 'active' or parts[1] != 'HKCU':
            messagebox.showinfo('Недоступно', 'Можно отключать только активные записи HKCU.')
            return
        name = parts[2]
        if not messagebox.askyesno('Автозагрузка', f'Отключить «{name}»?\n\n'
                'WinPilot сохранит значение для возможного восстановления.'):
            return
        self._task(f'Отключение автозагрузки {name}', lambda: core.disable_startup(name),
                   lambda _: self._refresh_startup())

    def _restore_selected(self):
        parts = self._selected_startup()
        if not parts:
            return
        if parts[0] != 'disabled':
            messagebox.showinfo('Недоступно', 'Выберите запись со статусом «Отключена (WinPilot)».')
            return
        name = parts[1]
        if not messagebox.askyesno('Автозагрузка', f'Восстановить запуск «{name}» при входе в Windows?'):
            return
        self._task(f'Восстановление автозагрузки {name}', lambda: core.restore_startup(name),
                   lambda _: self._refresh_startup())

    def _open_startup_settings(self):
        try:
            core.open_windows_startup()
        except Exception as exc:
            messagebox.showerror('WinPilot', str(exc))

    def _page_tweaks(self, body):
        self._heading(body, 'Настройки Windows',
                      'Три прозрачных изменения реестра и управление существующей схемой питания. Можно откатить.')
        try:
            configs = core.tweaks()
        except Exception as exc:
            self._label(body, str(exc), 11, WARN).pack(anchor='w')
            return
        for t in configs:
            card = self._card(body)
            card.pack(fill='x', pady=(0, 10))
            inner = tk.Frame(card, bg=PANEL)
            inner.pack(fill='x', padx=18, pady=13)
            labelgroup = tk.Frame(inner, bg=PANEL)
            labelgroup.pack(side='left', fill='x', expand=True)
            self._label(labelgroup, t.label, 12, FG, True, bg=PANEL).pack(anchor='w')
            self._label(labelgroup, t.description, 9, MUTED, bg=PANEL,
                        wraplength=455).pack(anchor='w', pady=(3, 0))
            btns = tk.Frame(inner, bg=PANEL)
            btns.pack(side='right')
            self._button(btns, 'Применить', lambda cfg=t: self._apply_tweak(cfg),
                         primary=True).pack(side='left', padx=(0, 8))
            self._button(btns, 'Откатить', lambda cfg=t: self._restore_tweak(cfg)).pack(side='left')
        power = self._card(body)
        power.pack(fill='x', pady=(10, 0))
        self._label(power, 'Схема питания', 13, FG, True, bg=PANEL).pack(anchor='w', padx=18, pady=(18, 5))
        self._label(power, 'Высокая производительность увеличивает расход энергии и нагрев. '
                    'В играх прирост не гарантирован.',
                    9, MUTED, bg=PANEL, wraplength=680).pack(anchor='w', padx=18)
        area = tk.Frame(power, bg=PANEL)
        area.pack(fill='x', padx=18, pady=(13, 19))
        self.power_choice = ttk.Combobox(area, state='readonly', width=48)
        self.power_choice.pack(side='left', padx=(0, 9))
        self._button(area, 'Применить', self._apply_power).pack(side='left', padx=(0, 7))
        self._button(area, 'Вернуть прежнюю', self._restore_power).pack(side='left')
        self._task('Получение схем питания', core.power_plans, self._power_ready)

    def _apply_tweak(self, t: core.Tweak):
        try:
            applied, _ = core.tweak_status(t)
            if applied:
                messagebox.showinfo('Настройка', 'Параметр уже имеет выбранное значение.')
                return
        except Exception as exc:
            messagebox.showerror('WinPilot', str(exc))
            return
        if not messagebox.askyesno('Применение', f'{t.label}?\n\n{t.description}\n\n'
                                     'Для полного применения может потребоваться перезапуск Проводника или вход в систему.'):
            return
        self._task(f'Применение: {t.label}', lambda: core.apply_tweak(t),
                   lambda _: messagebox.showinfo('WinPilot', 'Изменение применено. Резервная копия сохранена.'))

    def _restore_tweak(self, t: core.Tweak):
        if not messagebox.askyesno('Откат', f'Вернуть прежнее значение параметра «{t.label}»?'):
            return
        self._task(f'Откат: {t.label}', lambda: core.restore_tweak(t),
                   lambda _: messagebox.showinfo('WinPilot', 'Исходное значение восстановлено.'))

    def _power_ready(self, result):
        if self.current_page != 'tweaks':
            return
        plans, active = result
        self.power_map = {f'{name}  [{guid[:8]}]': guid for guid, name in plans}
        names = list(self.power_map.keys())
        self.power_choice['values'] = names
        for i, name in enumerate(names):
            if self.power_map[name] == active:
                self.power_choice.current(i)
                return
        if names:
            self.power_choice.current(0)

    def _apply_power(self):
        if not getattr(self, 'power_map', None):
            messagebox.showinfo('WinPilot', 'Список схем питания ещё не загружен.')
            return
        guid = self.power_map.get(self.power_choice.get())
        if not guid:
            return
        if not messagebox.askyesno('Схема питания',
                                   'Активировать выбранную схему питания?\n'
                                   'Она может повлиять на энергопотребление и температуру.'):
            return
        self._task('Смена схемы питания', lambda: core.set_power_plan(guid),
                   lambda _: messagebox.showinfo('WinPilot', 'Схема питания изменена.'))

    def _restore_power(self):
        if not messagebox.askyesno('Схема питания', 'Восстановить ранее сохранённую схему питания?'):
            return
        self._task('Откат схемы питания', core.restore_power_plan,
                   lambda _: self.show_page('tweaks'))

    def _page_diagnostics(self, body):
        self._heading(body, 'Диагностика и обслуживание',
                      'Запуск встроенных инструментов Windows без автоматического изменения системных служб.')
        rows = [
            ('Системная автозагрузка',
             'Откроет стандартный экран Windows со всеми приложениями автозапуска.',
             'Открыть', self._open_startup_settings),
            ('Очистка кэша DNS',
             'Сбрасывает локальные DNS-записи. Это не увеличивает скорость интернета.',
             'Очистить DNS', self._confirm_dns),
            ('Папка резервных копий',
             'Откроет каталог с журналом и сохранёнными предыдущими значениями.',
             'Открыть папку', self._open_app_folder),
        ]
        for title, desc, btn, cmd in rows:
            card = self._card(body)
            card.pack(fill='x', pady=(0, 13))
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill='x', padx=19, pady=18)
            txt = tk.Frame(row, bg=PANEL)
            txt.pack(side='left', fill='x', expand=True)
            self._label(txt, title, 13, FG, True, bg=PANEL).pack(anchor='w')
            self._label(txt, desc, 9, MUTED, bg=PANEL,
                        wraplength=550).pack(anchor='w', pady=(4, 0))
            self._button(row, btn, cmd).pack(side='right')

    def _confirm_dns(self):
        if messagebox.askyesno('DNS', 'Очистить кэш DNS Windows?'):
            self._task('Очистка кэша DNS', core.flush_dns,
                       lambda text: messagebox.showinfo('DNS', text))

    def _open_app_folder(self):
        try:
            core.APP_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(core.APP_DIR)
        except Exception as exc:
            messagebox.showerror('WinPilot', str(exc))

    def _page_logs(self, body):
        self._heading(body, 'Журнал операций',
                      'Программа не отправляет данные в интернет. Журнал хранится локально в AppData.')
        frame = self._card(body)
        frame.pack(fill='both', expand=True)
        txt = tk.Text(frame, bg=PANEL, fg=FG, font=('Consolas', 10), wrap='word',
                      borderwidth=0, highlightthickness=0, padx=16, pady=16, insertbackground=FG)
        scr = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True)
        path = core.APP_DIR / 'operations.log'
        content = path.read_text(encoding='utf-8', errors='replace') if path.exists() else 'Пока операций нет.'
        txt.insert('1.0', content[-120000:])
        txt.configure(state='disabled')
        self._button(body, 'Обновить журнал', lambda: self.show_page('logs')).pack(anchor='w', pady=(14, 0))


def launch() -> None:
    core.ensure_windows()
    root = tk.Tk()
    WinPilotApp(root)
    root.mainloop()
