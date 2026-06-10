import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser, font as tkfont

import serial
import serial.tools.list_ports

BASE_DIR = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
SETTINGS_FILE = BASE_DIR / 'serial_reader_settings.json'
DEFAULT_LOG_FILE = BASE_DIR / 'log_serial.txt'
BAUDRATE = 115200
TIMEOUT = 1
RETRY_DELAY = 3
ESPTOOL_CHIP = 'esp32s3'
ESPTOOL_ADDR = '0x0'

ser = None
reader_thread = None
stop_event = threading.Event()
pause_event = threading.Event()
ui_queue = queue.Queue()
log_buffer = []
root = None
style = None
current_theme_name = 'dark'
theme = {}

settings = {
    'theme': 'dark',
    'last_port': '',
    'auto_save': True,
    'log_file': str(DEFAULT_LOG_FILE),
    'font_family': 'Consolas',
    'font_size': 10,
    'font_color': '',
    'log_bg': '',
    'last_command': '',
    'last_bin': '',
}

THEMES = {
    'dark': {
        'bg': '#0f172a',
        'card': '#111827',
        'text': '#e5e7eb',
        'muted': '#94a3b8',
        'entry_bg': '#0b1220',
        'entry_fg': '#e5e7eb',
        'log_bg': '#0b1220',
        'log_fg': '#e5e7eb',
        'success': '#34d399',
        'warning': '#fbbf24',
        'error': '#f87171',
    },
    'light': {
        'bg': '#f4f6f9',
        'card': '#ffffff',
        'text': '#111827',
        'muted': '#4b5563',
        'entry_bg': '#ffffff',
        'entry_fg': '#111827',
        'log_bg': '#ffffff',
        'log_fg': '#111827',
        'success': '#047857',
        'warning': '#b45309',
        'error': '#b91c1c',
    },
}

widgets = {}


def load_settings():
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                settings.update(loaded)
    except Exception:
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def remover_ansi(texto: str) -> str:
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', texto)


def agora_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def portas_disponiveis():
    items = []
    for p in serial.tools.list_ports.comports():
        desc = p.description or 'Dispositivo serial'
        items.append(f'{p.device} - {desc}')
    return items


def extrair_porta(item_combo: str) -> str:
    return item_combo.split(' - ')[0].strip() if item_combo else ''


def is_error_line(texto: str) -> bool:
    s = texto.lower()
    palavras = [' erro ', 'error', 'fail', 'falha', 'exception', 'timeout', 'failed', 'conexão perdida', 'conexao perdida']
    return any(p in f' {s} ' for p in palavras)


def safe_messagebox_error(title: str, msg: str):
    try:
        messagebox.showerror(title, msg)
    except Exception:
        print(f'{title}: {msg}')


def open_port(port: str):
    return serial.Serial(port, BAUDRATE, timeout=TIMEOUT)


def selected_port() -> str:
    return extrair_porta(widgets['combo_ports'].get())


def is_reader_running() -> bool:
    return bool(reader_thread and reader_thread.is_alive() and not stop_event.is_set())


def update_status(text: str, color: str = None):
    if color is None:
        color = theme['text']
    widgets['status_var'].set(text)
    widgets['status_label'].configure(fg=color)


def update_status_threadsafe(text: str, color: str = None):
    ui_queue.put(('status', text, color))


def append_log_line(line: str):
    text = widgets['text_log']
    text.configure(state='normal')
    tag = 'error' if is_error_line(line) else 'normal'
    text.insert(tk.END, line + '\n', tag)
    text.see(tk.END)
    text.configure(state='disabled')


def apply_log_style():
    try:
        fam = widgets['font_var'].get().strip() or 'Consolas'
        size = int(widgets['size_var'].get())
        widgets['text_log'].configure(font=(fam, size))
    except Exception:
        pass

    try:
        fg = widgets['font_color_var'].get().strip()
        bg = widgets['log_bg_var'].get().strip()
        if fg:
            widgets['text_log'].configure(fg=fg)
            widgets['text_log'].tag_configure('normal', foreground=fg)
        if bg:
            widgets['text_log'].configure(bg=bg)
    except Exception:
        pass


def apply_theme():
    global theme
    theme = THEMES[current_theme_name]

    root.configure(bg=theme['bg'])
    style.configure('App.TFrame', background=theme['bg'])
    style.configure('Card.TFrame', background=theme['card'])
    style.configure('App.TLabel', background=theme['bg'], foreground=theme['text'])
    style.configure('Card.TLabel', background=theme['card'], foreground=theme['text'])
    style.configure('Title.TLabel', background=theme['bg'], foreground=theme['text'], font=('Segoe UI', 17, 'bold'))
    style.configure('Muted.TLabel', background=theme['bg'], foreground=theme['muted'], font=('Segoe UI', 10))
    style.configure('CardMuted.TLabel', background=theme['card'], foreground=theme['muted'])
    style.configure('TButton', font=('Segoe UI', 10), padding=7)
    style.configure('TCombobox', padding=5)
    style.configure('TSpinbox', padding=5)
    style.configure('TCheckbutton', background=theme['card'], foreground=theme['text'], font=('Segoe UI', 10))

    widgets['entry_file'].configure(bg=theme['entry_bg'], fg=theme['entry_fg'], insertbackground=theme['entry_fg'])
    widgets['entry_cmd'].configure(bg=theme['entry_bg'], fg=theme['entry_fg'], insertbackground=theme['entry_fg'])
    widgets['entry_bin'].configure(bg=theme['entry_bg'], fg=theme['entry_fg'], insertbackground=theme['entry_fg'])
    widgets['text_log'].configure(bg=theme['log_bg'], fg=theme['log_fg'], insertbackground=theme['log_fg'])
    widgets['status_label'].configure(bg=theme['bg'], fg=theme['text'])
    widgets['text_log'].tag_configure('normal', foreground=theme['log_fg'])
    widgets['text_log'].tag_configure('error', foreground=theme['error'])
    widgets['text_log'].tag_configure('timestamp', foreground=theme['muted'])
    widgets['btn_theme'].configure(text='Tema claro' if current_theme_name == 'dark' else 'Tema escuro')


def toggle_theme():
    global current_theme_name
    current_theme_name = 'light' if current_theme_name == 'dark' else 'dark'
    settings['theme'] = current_theme_name
    save_settings()
    apply_theme()
    update_status(f'Tema {current_theme_name} ativado.', theme['success'])


def copy_visible_log():
    try:
        text = widgets['text_log'].get('1.0', tk.END).strip()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        update_status('Log copiado.', theme['success'])
    except Exception as e:
        safe_messagebox_error('Erro', f'Não foi possível copiar o log: {e}')


def clear_visible_log():
    try:
        text = widgets['text_log']
        text.configure(state='normal')
        text.delete('1.0', tk.END)
        text.configure(state='disabled')
        update_status('Tela limpa. Histórico mantido.', theme['warning'])
    except Exception as e:
        safe_messagebox_error('Erro', f'Não foi possível limpar a tela: {e}')


def choose_log_file():
    try:
        current = widgets['file_var'].get().strip() or str(DEFAULT_LOG_FILE)
        path = filedialog.asksaveasfilename(
            title='Salvar log como',
            defaultextension='.txt',
            filetypes=[('Arquivo de texto', '*.txt'), ('Todos os arquivos', '*.*')],
            initialfile=Path(current).name,
        )
        if path:
            widgets['file_var'].set(path)
            settings['log_file'] = path
            save_settings()
    except Exception as e:
        safe_messagebox_error('Erro', str(e))


def save_log_manual():
    try:
        path = widgets['file_var'].get().strip()
        if not path:
            raise ValueError('Informe um arquivo para salvar.')
        with open(path, 'w', encoding='utf-8') as f:
            for line in log_buffer:
                f.write(line + '\n')
        settings['log_file'] = path
        settings['auto_save'] = widgets['auto_var'].get()
        save_settings()
        update_status(f'Log salvo em {path}', theme['success'])
    except Exception as e:
        safe_messagebox_error('Erro ao salvar', str(e))


def choose_color(var_name: str):
    c = colorchooser.askcolor(title='Escolher cor')
    if c and c[1]:
        widgets[var_name].set(c[1])


def open_personalization():
    win = tk.Toplevel(root)
    win.title('Personalização do log')
    win.geometry('360x180')
    win.resizable(False, False)
    win.configure(bg=theme['bg'])
    win.transient(root)
    win.grab_set()

    frm = ttk.Frame(win, padding=12, style='Card.TFrame')
    frm.pack(fill='both', expand=True)

    ttk.Label(frm, text='Fonte', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=4)
    ttk.Combobox(frm, textvariable=widgets['font_var'], values=sorted(set(tkfont.families(root))), width=24).grid(row=0, column=1, sticky='ew', pady=4)

    ttk.Label(frm, text='Tamanho', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=4)
    ttk.Spinbox(frm, from_=8, to=24, textvariable=widgets['size_var'], width=8).grid(row=1, column=1, sticky='w', pady=4)

    ttk.Button(frm, text='Cor da fonte', command=lambda: choose_color('font_color_var')).grid(row=2, column=0, sticky='ew', pady=(10, 4))
    ttk.Button(frm, text='Cor de fundo', command=lambda: choose_color('log_bg_var')).grid(row=2, column=1, sticky='ew', pady=(10, 4))

    ttk.Button(frm, text='Aplicar', command=lambda: finish_personalization(win)).grid(row=3, column=1, sticky='e', pady=(12, 0))
    frm.columnconfigure(1, weight=1)


def finish_personalization(win):
    try:
        settings['font_family'] = widgets['font_var'].get().strip() or 'Consolas'
        try:
            settings['font_size'] = int(widgets['size_var'].get())
        except Exception:
            settings['font_size'] = 10
        settings['font_color'] = widgets['font_color_var'].get().strip()
        settings['log_bg'] = widgets['log_bg_var'].get().strip()
        save_settings()
        apply_log_style()
        update_status('Personalização aplicada.', theme['success'])
        win.destroy()
    except Exception as e:
        safe_messagebox_error('Erro', str(e))


def write_serial_output_line(line: str):
    log_buffer.append(line)
    append_log_line(line)
    widgets['count_var'].set(f'Linhas: {len(log_buffer)}')
    if widgets['auto_var'].get():
        path = widgets['file_var'].get().strip() or str(DEFAULT_LOG_FILE)
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception as e:
            update_status(f'Falha ao salvar automaticamente: {e}', theme['error'])


def reader_worker(port: str):
    global ser
    while not stop_event.is_set():
        try:
            update_status_threadsafe(f'Conectando em {port}...', theme['muted'])
            ser = open_port(port)
            update_status_threadsafe(f'Conectado em {port}', theme['success'])

            while not stop_event.is_set() and ser and ser.is_open:
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue

                try:
                    raw = ser.readline().decode(errors='ignore').strip()
                    raw = remover_ansi(raw)
                    if not raw:
                        continue

                    line = f"{agora_str()} - {raw}"
                    ui_queue.put(('log', line))

                except (serial.SerialException, OSError) as e:
                    ui_queue.put(('status', f'Conexão perdida: {e}', theme['error']))
                    break
                except Exception as e:
                    ui_queue.put(('status', f'Erro de leitura: {e}', theme['error']))
                    break

        except serial.SerialException as e:
            update_status_threadsafe(f'Falha ao conectar: {e}', theme['error'])
            time.sleep(RETRY_DELAY)
        except Exception as e:
            update_status_threadsafe(f'Erro inesperado: {e}', theme['error'])
            time.sleep(RETRY_DELAY)
        finally:
            try:
                if ser and ser.is_open:
                    ser.close()
            except Exception:
                pass

            if not stop_event.is_set():
                update_status_threadsafe(f'Tentando reconectar em {RETRY_DELAY}s...', theme['warning'])
                time.sleep(RETRY_DELAY)

    update_status_threadsafe('Leitura parada.', theme['muted'])


def refresh_ports(select_last=True):
    ports = portas_disponiveis()
    widgets['combo_ports']['values'] = ports

    selected = ''
    last = settings.get('last_port', '').strip()
    if select_last and last:
        for item in ports:
            if extrair_porta(item) == last:
                selected = item
                break

    if selected:
        widgets['combo_ports'].set(selected)
    elif ports:
        widgets['combo_ports'].current(0)
    else:
        widgets['combo_ports'].set('')

    update_status('Portas atualizadas.', theme['success'] if ports else theme['warning'])


def stop_reading(wait=False):
    global ser, reader_thread
    stop_event.set()
    pause_event.clear()
    try:
        if ser and ser.is_open:
            ser.close()
    except Exception:
        pass

    if wait and reader_thread and reader_thread.is_alive():
        reader_thread.join(timeout=2.0)

    widgets['btn_start'].configure(state='normal')
    widgets['btn_stop'].configure(state='disabled')
    widgets['btn_pause'].configure(state='disabled', text='Pausar')


def start_reading(port_override=None):
    global reader_thread

    if reader_thread and reader_thread.is_alive():
        messagebox.showinfo('Informação', 'A leitura já está em execução.')
        return

    port = port_override or selected_port()
    if not port:
        messagebox.showwarning('Atenção', 'Selecione uma porta serial disponível.')
        return

    settings['last_port'] = port
    settings['theme'] = current_theme_name
    settings['auto_save'] = widgets['auto_var'].get()
    settings['log_file'] = widgets['file_var'].get().strip() or str(DEFAULT_LOG_FILE)
    save_settings()

    stop_event.clear()
    pause_event.clear()
    widgets['btn_pause'].configure(text='Pausar')

    try:
        reader_thread = threading.Thread(target=reader_worker, args=(port,), daemon=True)
        reader_thread.start()
        widgets['btn_start'].configure(state='disabled')
        widgets['btn_stop'].configure(state='normal')
        widgets['btn_pause'].configure(state='normal')
        update_status(f'Iniciando leitura em {port}...', theme['success'])
    except Exception as e:
        safe_messagebox_error('Erro', f'Não foi possível iniciar a leitura: {e}')


def pause_resume():
    if pause_event.is_set():
        pause_event.clear()
        widgets['btn_pause'].configure(text='Pausar')
        update_status('Leitura retomada.', theme['success'])
    else:
        pause_event.set()
        widgets['btn_pause'].configure(text='Retomar')
        update_status('Leitura pausada.', theme['warning'])


def send_command():
    port = selected_port()
    cmd = widgets['cmd_var'].get().strip()
    if not port:
        messagebox.showwarning('Atenção', 'Selecione uma porta serial.')
        return
    if not cmd:
        messagebox.showwarning('Atenção', 'Digite um comando para enviar.')
        return

    was_running = is_reader_running()
    if was_running:
        stop_reading(wait=True)

    def worker():
        temp_ser = None
        try:
            update_status_threadsafe('Enviando comando...', theme['muted'])
            temp_ser = open_port(port)
            time.sleep(0.15)
            temp_ser.reset_input_buffer()
            temp_ser.write((cmd + '\r\n').encode('utf-8'))
            temp_ser.flush()

            response_start = time.time()
            response_lines = []
            while time.time() - response_start < 1.2:
                try:
                    if temp_ser.in_waiting:
                        raw = temp_ser.readline().decode(errors='ignore').strip()
                        raw = remover_ansi(raw)
                        if raw:
                            response_lines.append(raw)
                    else:
                        time.sleep(0.05)
                except Exception:
                    break

            ui_queue.put(('log', f'{agora_str()} - [COMANDO ENVIADO] {cmd}'))
            for resp in response_lines:
                ui_queue.put(('log', f'{agora_str()} - [RESPOSTA] {resp}'))
            update_status_threadsafe('Comando enviado.', theme['success'])
        except Exception as e:
            update_status_threadsafe(f'Erro ao enviar comando: {e}', theme['error'])
        finally:
            try:
                if temp_ser:
                    temp_ser.close()
            except Exception:
                pass
            if was_running:
                ui_queue.put(('restart_reading', port))

    threading.Thread(target=worker, daemon=True).start()
    settings['last_command'] = cmd
    save_settings()


def browse_bin():
    path = filedialog.askopenfilename(
        title='Selecionar firmware .bin',
        filetypes=[('Firmware binário', '*.bin'), ('Todos os arquivos', '*.*')],
    )
    if path:
        widgets['bin_var'].set(path)
        settings['last_bin'] = path
        save_settings()


def flash_firmware():
    port = selected_port()
    bin_path = widgets['bin_var'].get().strip()

    if not port:
        messagebox.showwarning('Atenção', 'Selecione uma porta serial.')
        return
    if not bin_path:
        messagebox.showwarning('Atenção', 'Selecione o arquivo .bin.')
        return
    if not Path(bin_path).exists():
        messagebox.showerror('Erro', 'O arquivo .bin selecionado não existe.')
        return

    if is_reader_running():
        stop_reading(wait=True)

    def worker():
        try:
            update_status_threadsafe('Iniciando gravação do firmware...', theme['warning'])
            cmd = [
                sys.executable,
                '-m', 'esptool',
                '-p', port,
                '-b', str(BAUDRATE),
                '-c', ESPTOOL_CHIP,
                'write_flash',
                ESPTOOL_ADDR,
                bin_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            output = (result.stdout or '') + (('\n' + result.stderr) if result.stderr else '')

            for raw in output.splitlines():
                line = remover_ansi(raw).strip()
                if line:
                    ui_queue.put(('log', f'{agora_str()} - {line}'))

            if result.returncode == 0:
                update_status_threadsafe('Firmware gravado com sucesso.', theme['success'])
            else:
                update_status_threadsafe(f'Falha ao gravar firmware (código {result.returncode}).', theme['error'])
        except Exception as e:
            update_status_threadsafe(f'Erro ao gravar firmware: {e}', theme['error'])

    threading.Thread(target=worker, daemon=True).start()
    settings['last_bin'] = bin_path
    save_settings()


def process_ui_queue():
    try:
        while True:
            kind, *data = ui_queue.get_nowait()
            if kind == 'log':
                write_serial_output_line(data[0])
            elif kind == 'status':
                text = data[0]
                color = data[1] if len(data) > 1 and data[1] else theme['text']
                update_status(text, color)
            elif kind == 'restart_reading':
                port = data[0] if data else ''
                if port:
                    widgets['combo_ports'].set(next((p for p in widgets['combo_ports']['values'] if extrair_porta(p) == port), ''))
                    start_reading(port_override=port)
    except queue.Empty:
        pass
    root.after(100, process_ui_queue)


def build_ui():
    global root, style

    root = tk.Tk()
    root.title('Leitor Serial Pro')
    root.geometry('1200x760')
    root.minsize(1060, 650)

    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    style.configure('App.TFrame', background=THEMES[current_theme_name]['bg'])
    style.configure('Card.TFrame', background=THEMES[current_theme_name]['card'])
    style.configure('App.TLabel', background=THEMES[current_theme_name]['bg'], foreground=THEMES[current_theme_name]['text'])
    style.configure('Card.TLabel', background=THEMES[current_theme_name]['card'], foreground=THEMES[current_theme_name]['text'])
    style.configure('Title.TLabel', background=THEMES[current_theme_name]['bg'], foreground=THEMES[current_theme_name]['text'], font=('Segoe UI', 17, 'bold'))
    style.configure('Muted.TLabel', background=THEMES[current_theme_name]['bg'], foreground=THEMES[current_theme_name]['muted'], font=('Segoe UI', 10))
    style.configure('CardMuted.TLabel', background=THEMES[current_theme_name]['card'], foreground=THEMES[current_theme_name]['muted'])
    style.configure('TButton', font=('Segoe UI', 10), padding=7)
    style.configure('TCombobox', padding=5)
    style.configure('TSpinbox', padding=5)
    style.configure('TCheckbutton', background=THEMES[current_theme_name]['card'], foreground=THEMES[current_theme_name]['text'], font=('Segoe UI', 10))

    main = ttk.Frame(root, padding=14, style='App.TFrame')
    main.pack(fill='both', expand=True)

    header = ttk.Frame(main, style='App.TFrame')
    header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
    header.columnconfigure(0, weight=1)

    ttk.Label(header, text='Leitor Serial Pro', style='Title.TLabel').grid(row=0, column=0, sticky='w')
    ttk.Label(header, text='Controles na lateral e log ocupando a altura total da tela.', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 0))

    widgets['count_var'] = tk.StringVar(value='Linhas: 0')
    ttk.Label(header, textvariable=widgets['count_var'], style='App.TLabel', font=('Segoe UI', 10, 'bold')).grid(row=0, column=1, rowspan=2, sticky='e')

    sidebar = ttk.Frame(main, style='App.TFrame', width=380)
    sidebar.grid(row=1, column=0, sticky='nsw', padx=(0, 12))
    sidebar.grid_propagate(False)

    log_area = ttk.Frame(main, style='App.TFrame')
    log_area.grid(row=1, column=1, sticky='nsew')
    main.rowconfigure(1, weight=1)
    main.columnconfigure(1, weight=1)

    def card(parent, title_text):
        f = ttk.Frame(parent, style='Card.TFrame', padding=10)
        f.pack(fill='x', pady=(0, 10))
        ttk.Label(f, text=title_text, style='Card.TLabel').pack(anchor='w', pady=(0, 8))
        return f

    card_conn = card(sidebar, 'Conexão')
    row = ttk.Frame(card_conn, style='Card.TFrame')
    row.pack(fill='x')
    ttk.Label(row, text='Porta:', style='Card.TLabel').pack(side='left')
    combo_ports = ttk.Combobox(row, width=30, state='readonly')
    combo_ports.pack(side='left', padx=(8, 0), fill='x', expand=True)

    row2 = ttk.Frame(card_conn, style='Card.TFrame')
    row2.pack(fill='x', pady=(8, 0))
    btn_refresh = ttk.Button(row2, text='Atualizar portas', command=lambda: refresh_ports(select_last=True))
    btn_refresh.pack(side='left')
    btn_start = ttk.Button(row2, text='Iniciar', command=start_reading)
    btn_start.pack(side='left', padx=(8, 0))
    btn_stop = ttk.Button(row2, text='Parar', command=stop_reading, state='disabled')
    btn_stop.pack(side='left', padx=(8, 0))
    btn_pause = ttk.Button(row2, text='Pausar', command=pause_resume, state='disabled')
    btn_pause.pack(side='left', padx=(8, 0))

    card_logfile = card(sidebar, 'Salvamento')
    auto_var = tk.BooleanVar(value=bool(settings.get('auto_save', True)))
    ttk.Checkbutton(card_logfile, text='Salvar automaticamente', variable=auto_var).pack(anchor='w', pady=(0, 6))
    row = ttk.Frame(card_logfile, style='Card.TFrame')
    row.pack(fill='x')
    ttk.Label(row, text='Arquivo:', style='Card.TLabel').pack(side='left')
    entry_file = tk.Entry(row, width=24)
    entry_file.pack(side='left', padx=(8, 0), fill='x', expand=True)
    entry_file.insert(0, settings.get('log_file', str(DEFAULT_LOG_FILE)))
    rowb = ttk.Frame(card_logfile, style='Card.TFrame')
    rowb.pack(fill='x', pady=(8, 0))
    ttk.Button(rowb, text='Escolher...', command=choose_log_file).pack(side='left')
    ttk.Button(rowb, text='Salvar agora', command=save_log_manual).pack(side='left', padx=(8, 0))
    ttk.Button(rowb, text='Limpar tela', command=clear_visible_log).pack(side='left', padx=(8, 0))
    ttk.Button(rowb, text='Copiar log', command=copy_visible_log).pack(side='left', padx=(8, 0))

    card_tools = card(sidebar, 'Ações')
    ttk.Label(card_tools, text='Comando para o rastreador:', style='Card.TLabel').pack(anchor='w')
    entry_cmd = tk.Entry(card_tools)
    entry_cmd.pack(fill='x', pady=(4, 0))
    entry_cmd.insert(0, settings.get('last_command', ''))
    ttk.Button(card_tools, text='Enviar comando', command=send_command).pack(anchor='e', pady=(6, 10))

    ttk.Label(card_tools, text='Firmware .bin:', style='Card.TLabel').pack(anchor='w')
    entry_bin = tk.Entry(card_tools)
    entry_bin.pack(fill='x', pady=(4, 0))
    entry_bin.insert(0, settings.get('last_bin', ''))
    rowf = ttk.Frame(card_tools, style='Card.TFrame')
    rowf.pack(fill='x', pady=(6, 0))
    ttk.Button(rowf, text='Selecionar .bin', command=browse_bin).pack(side='left')
    ttk.Button(rowf, text='Gravar firmware', command=flash_firmware).pack(side='left', padx=(8, 0))

    card_theme = card(sidebar, 'Visual')
    btn_theme = ttk.Button(card_theme, command=toggle_theme)
    btn_theme.pack(side='left')
    ttk.Button(card_theme, text='Personalização do log', command=open_personalization).pack(side='left', padx=(8, 0))
    ttk.Label(card_theme, text='A tela de log não pode ser editada.', style='CardMuted.TLabel').pack(anchor='w', pady=(8, 0))

    log_card = ttk.Frame(log_area, style='Card.TFrame', padding=10)
    log_card.pack(fill='both', expand=True)

    text_log = tk.Text(
        log_card,
        wrap='none',
        relief='flat',
        borderwidth=0,
        undo=False,
        state='disabled',
        font=(settings.get('font_family', 'Consolas'), int(settings.get('font_size', 10))),
    )
    text_log.pack(side='left', fill='both', expand=True)
    scroll_y = ttk.Scrollbar(log_card, orient='vertical', command=text_log.yview)
    scroll_y.pack(side='right', fill='y')
    text_log.configure(yscrollcommand=scroll_y.set)

    status_frame = ttk.Frame(main, style='App.TFrame')
    status_frame.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(10, 0))
    status_var = tk.StringVar(value='Pronto para iniciar.')
    status_label = tk.Label(status_frame, textvariable=status_var, anchor='w')
    status_label.pack(anchor='w')

    widgets.update({
        'combo_ports': combo_ports,
        'btn_start': btn_start,
        'btn_stop': btn_stop,
        'btn_pause': btn_pause,
        'btn_theme': btn_theme,
        'btn_refresh': btn_refresh,
        'file_var': tk.StringVar(value=settings.get('log_file', str(DEFAULT_LOG_FILE))),
        'auto_var': auto_var,
        'entry_file': entry_file,
        'entry_cmd': entry_cmd,
        'entry_bin': entry_bin,
        'cmd_var': tk.StringVar(value=settings.get('last_command', '')),
        'bin_var': tk.StringVar(value=settings.get('last_bin', '')),
        'text_log': text_log,
        'status_var': status_var,
        'status_label': status_label,
        'font_var': tk.StringVar(value=settings.get('font_family', 'Consolas')),
        'size_var': tk.StringVar(value=str(settings.get('font_size', 10))),
        'font_color_var': tk.StringVar(value=settings.get('font_color', '')),
        'log_bg_var': tk.StringVar(value=settings.get('log_bg', '')),
    })

    entry_file.configure(textvariable=widgets['file_var'])
    entry_cmd.configure(textvariable=widgets['cmd_var'])
    entry_bin.configure(textvariable=widgets['bin_var'])

    apply_theme()
    apply_log_style()
    refresh_ports(select_last=True)
    process_ui_queue()

    def auto_start_last_port():
        try:
            last_port = settings.get('last_port', '').strip()
            if not last_port:
                return
            for item in portas_disponiveis():
                if extrair_porta(item) == last_port:
                    combo_ports.set(item)
                    start_reading(port_override=last_port)
                    return
            update_status(f'Última porta usada ({last_port}) não está disponível.', theme['warning'])
        except Exception as e:
            update_status(f'Auto-início falhou: {e}', theme['error'])

    root.after(700, auto_start_last_port)

    entry_cmd.bind('<Return>', lambda event=None: send_command())
    entry_bin.bind('<Return>', lambda event=None: flash_firmware())

    def on_close():
        try:
            settings['theme'] = current_theme_name
            settings['auto_save'] = widgets['auto_var'].get()
            settings['log_file'] = widgets['file_var'].get().strip() or str(DEFAULT_LOG_FILE)
            settings['last_command'] = widgets['cmd_var'].get().strip()
            settings['last_bin'] = widgets['bin_var'].get().strip()
            save_settings()
        except Exception:
            pass

        if not widgets['auto_var'].get() and log_buffer:
            try:
                if messagebox.askyesno('Salvar log', 'O salvamento automático está desligado. Deseja salvar o log antes de sair?'):
                    save_log_manual()
            except Exception:
                pass

        stop_reading(wait=False)
        root.after(150, root.destroy)

    root.protocol('WM_DELETE_WINDOW', on_close)
    return root


def process_ui_queue():
    try:
        while True:
            kind, *data = ui_queue.get_nowait()
            if kind == 'log':
                write_serial_output_line(data[0])
            elif kind == 'status':
                text = data[0]
                color = data[1] if len(data) > 1 and data[1] else theme['text']
                update_status(text, color)
            elif kind == 'restart_reading':
                port = data[0] if data else ''
                if port:
                    widgets['combo_ports'].set(next((p for p in widgets['combo_ports']['values'] if extrair_porta(p) == port), ''))
                    start_reading(port_override=port)
    except queue.Empty:
        pass
    root.after(100, process_ui_queue)


def main():
    load_settings()
    global current_theme_name
    current_theme_name = settings.get('theme', 'dark') if settings.get('theme') in THEMES else 'dark'
    app = build_ui()
    app.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        try:
            messagebox.showerror('Erro ao iniciar', err)
        except Exception:
            input('Erro ao iniciar. Pressione Enter para sair...')
