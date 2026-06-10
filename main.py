import json
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

# =========================================================
# CONFIG
# =========================================================
BASE_DIR = Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
SETTINGS_FILE = BASE_DIR / 'serial_reader_settings.json'
DEFAULT_LOG_FILE = BASE_DIR / 'log_serial.txt'
BAUDRATE = 115200
TIMEOUT = 1
RETRY_DELAY = 3
FLASH_ADDR_DEFAULT = '0x0'

# =========================================================
# THEMES
# =========================================================
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
        'info': '#4aa3ff',
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
        'info': '#1d4ed8',
    },
}

SMALL_BTN_STYLE = 'Small.TButton'

# Common ESP targets seen in current esptool docs and used in your devices.
CHIP_OPTIONS = [
    'auto',
    'esp32',
    'esp32s2',
    'esp32s3',
    'esp32c2',
    'esp32c3',
    'esp32c5',
    'esp32c6',
    'esp32c61',
    'esp32h2',
    'esp32p4',
    'esp8266',
]

# =========================================================
# SETTINGS
# =========================================================
def load_settings() -> dict:
    data = {
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
        'ai_api_key': '',
        'last_equip': 'RA24',
    }
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
    except Exception:
        pass
    return data


def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =========================================================
# HELPERS
# =========================================================
def strip_ansi(text: str) -> str:
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', text)


def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def list_serial_ports() -> list[str]:
    items = []
    for port in serial.tools.list_ports.comports():
        desc = port.description or 'Dispositivo serial'
        items.append(f'{port.device} - {desc}')
    return items


def extract_port(item: str) -> str:
    return item.split(' - ')[0].strip() if item else ''


def is_error_line(text: str) -> bool:
    s = f' {text.lower()} '
    keywords = [' erro ', 'error', 'fail', 'falha', 'exception', 'timeout', 'failed', 'conexão perdida', 'conexao perdida']
    return any(k in s for k in keywords)


def safe_messagebox_error(title: str, msg: str):
    try:
        messagebox.showerror(title, msg)
    except Exception:
        print(f'{title}: {msg}')


# =========================================================
# FIRMWARE WINDOW
# =========================================================
class FirmwareDialog:
    def __init__(self, app: 'SerialApp'):
        self.app = app
        self.root = app.root
        self.settings = app.settings
        self.theme = app.theme
        self.running = False
        self.proc = None
        self.queue = queue.Queue()

        self.win = tk.Toplevel(self.root)
        self.win.title('Atualização de firmware')
        self.win.geometry('780x560')
        self.win.minsize(720, 500)
        self.win.transient(self.root)
        self.win.grab_set()
        self.win.configure(bg=self.theme['bg'])

        self._build_ui()
        self._apply_theme()
        self.refresh_ports()
        self._process_queue()
        self.win.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build_ui(self):
        outer = ttk.Frame(self.win, padding=14, style='App.TFrame')
        outer.pack(fill='both', expand=True)

        top = ttk.Frame(outer, style='Card.TFrame', padding=12)
        top.pack(fill='x')

        ttk.Label(top, text='Enviar arquivo .bin', style='Card.TLabel', font=('Segoe UI', 13, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))

        ttk.Label(top, text='Porta:', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, state='readonly', width=36)
        self.port_combo.grid(row=1, column=1, sticky='ew', padx=(8, 8), pady=4)
        ttk.Button(top, text='Atualizar portas', style=SMALL_BTN_STYLE, command=self.refresh_ports).grid(row=1, column=2, sticky='w', pady=4)

        ttk.Label(top, text='Chip:', style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.chip_var = tk.StringVar(value='auto')
        self.chip_combo = ttk.Combobox(top, textvariable=self.chip_var, values=CHIP_OPTIONS, state='readonly', width=36)
        self.chip_combo.grid(row=2, column=1, sticky='ew', padx=(8, 8), pady=4)

        ttk.Label(top, text='Endereço:', style='Card.TLabel').grid(row=3, column=0, sticky='w', pady=4)
        self.addr_var = tk.StringVar(value=FLASH_ADDR_DEFAULT)
        self.addr_entry = tk.Entry(top, textvariable=self.addr_var)
        self.addr_entry.grid(row=3, column=1, sticky='ew', padx=(8, 8), pady=4)

        ttk.Label(top, text='Arquivo .bin:', style='Card.TLabel').grid(row=4, column=0, sticky='w', pady=4)
        self.bin_var = tk.StringVar(value=self.settings.get('last_bin', ''))
        self.bin_entry = tk.Entry(top, textvariable=self.bin_var)
        self.bin_entry.grid(row=4, column=1, sticky='ew', padx=(8, 8), pady=4)
        ttk.Button(top, text='Selecionar...', style=SMALL_BTN_STYLE, command=self.browse_bin).grid(row=4, column=2, sticky='w', pady=4)

        self.btn_start = ttk.Button(top, text='Gravar firmware', command=self.start_flash)
        self.btn_start.grid(row=5, column=1, sticky='e', pady=(12, 0))
        ttk.Button(top, text='Fechar', style=SMALL_BTN_STYLE, command=self._on_close).grid(row=5, column=2, sticky='w', padx=(8, 0), pady=(12, 0))
        top.columnconfigure(1, weight=1)

        mid = ttk.Frame(outer, style='Card.TFrame', padding=10)
        mid.pack(fill='both', expand=True, pady=(12, 0))

        self.status_var = tk.StringVar(value='Pronto para iniciar.')
        ttk.Label(mid, textvariable=self.status_var, style='Card.TLabel').pack(anchor='w')

        self.progress = ttk.Progressbar(mid, mode='indeterminate')
        self.progress.pack(fill='x', pady=(8, 10))

        self.output = tk.Text(mid, wrap='none', relief='flat', borderwidth=0, state='disabled', font=('Consolas', 10))
        self.output.pack(fill='both', expand=True)
        self.scroll = ttk.Scrollbar(mid, orient='vertical', command=self.output.yview)
        self.scroll.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=self.scroll.set)

    def _apply_theme(self):
        self.win.configure(bg=self.theme['bg'])
        self.output.configure(bg=self.theme['log_bg'], fg=self.theme['log_fg'], insertbackground=self.theme['log_fg'])
        self.output.tag_configure('normal', foreground=self.theme['log_fg'])
        self.output.tag_configure('error', foreground=self.theme['error'])
        self.output.tag_configure('info', foreground=self.theme['info'])
        self.output.tag_configure('success', foreground=self.theme['success'])
        self.output.tag_configure('warning', foreground=self.theme['warning'])

    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_combo['values'] = ports
        last = self.settings.get('last_port', '').strip()
        selected = ''
        for item in ports:
            if extract_port(item) == last:
                selected = item
                break
        if selected:
            self.port_var.set(selected)
        elif ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set('')
        self._push_status('Portas atualizadas.', 'success' if ports else 'warning')

    def browse_bin(self):
        path = filedialog.askopenfilename(
            title='Selecionar firmware .bin',
            filetypes=[('Firmware binário', '*.bin'), ('Todos os arquivos', '*.*')],
        )
        if path:
            self.bin_var.set(path)
            self.settings['last_bin'] = path
            save_settings(self.settings)

    def _append(self, line: str, tag: str = 'normal'):
        self.output.configure(state='normal')
        self.output.insert(tk.END, line + '\n', tag)
        self.output.see(tk.END)
        self.output.configure(state='disabled')

    def _push_status(self, text: str, tag: str = 'normal'):
        self.status_var.set(text)
        self._append(f'{now_str()} - {text}', tag)

    def start_flash(self):
        if self.running:
            return

        port = extract_port(self.port_var.get())
        chip = self.chip_var.get().strip() or 'auto'
        addr = self.addr_var.get().strip() or FLASH_ADDR_DEFAULT
        bin_path = self.bin_var.get().strip()

        if not port:
            messagebox.showwarning('Atenção', 'Selecione uma porta serial.')
            return
        if not bin_path:
            messagebox.showwarning('Atenção', 'Selecione o arquivo .bin.')
            return
        if not Path(bin_path).exists():
            messagebox.showerror('Erro', 'O arquivo .bin selecionado não existe.')
            return

        self.settings['last_port'] = port
        self.settings['last_bin'] = bin_path
        save_settings(self.settings)

        if self.app.is_reader_running():
            self.app.stop_reader(wait=True)

        self.running = True
        self.btn_start.configure(state='disabled')
        self.progress.start(12)
        self._append(f'{now_str()} - [FIRMWARE] Iniciando atualização...', 'info')
        self._push_status('Gravando firmware... acompanhe a janela.', 'warning')

        threading.Thread(target=self._flash_worker, args=(port, chip, addr, bin_path), daemon=True).start()

    def _flash_worker(self, port: str, chip: str, addr: str, bin_path: str):
        try:
            cmd = [sys.executable, '-m', 'esptool']
            if chip.lower() != 'auto':
                cmd += ['--chip', chip]
            cmd += ['-p', port, '-b', str(BAUDRATE), 'write-flash', addr, bin_path]

            self.queue.put(('append', f'{now_str()} - Comando: {' '.join(cmd)}', 'info'))
            self.queue.put(('status', 'Executando esptool...', 'warning'))

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            self.proc = proc

            for raw in iter(proc.stdout.readline, ''):
                if raw == '' and proc.poll() is not None:
                    break
                line = strip_ansi(raw).rstrip()
                if line:
                    tag = 'error' if is_error_line(line) else 'normal'
                    if any(word in line.lower() for word in ['writing', 'erasing', 'hash', 'connecting', 'detect', 'serial', 'flash', 'compress', 'compressed']):
                        self.queue.put(('status', line, 'warning'))
                    self.queue.put(('append', f'{now_str()} - {line}', tag))

            return_code = proc.wait()
            if return_code == 0:
                self.queue.put(('append', f'{now_str()} - [FIRMWARE] Concluído com sucesso.', 'success'))
                self.queue.put(('status', 'Firmware gravado com sucesso.', 'success'))
            else:
                self.queue.put(('append', f'{now_str()} - [FIRMWARE] Falha na gravação. Código: {return_code}', 'error'))
                self.queue.put(('status', f'Falha ao gravar firmware (código {return_code}).', 'error'))

        except FileNotFoundError:
            self.queue.put(('append', f'{now_str()} - [ERRO] Esptool não encontrado. Instale com: pip install esptool', 'error'))
            self.queue.put(('status', 'Esptool não encontrado.', 'error'))
        except Exception as e:
            self.queue.put(('append', f'{now_str()} - [ERRO] {e}', 'error'))
            self.queue.put(('status', f'Erro ao gravar firmware: {e}', 'error'))
        finally:
            self.queue.put(('done', None, None))

    def _process_queue(self):
        try:
            while True:
                kind, a, b = self.queue.get_nowait()
                if kind == 'append':
                    self._append(a, b)
                elif kind == 'status':
                    self.status_var.set(a)
                elif kind == 'done':
                    self.running = False
                    self.progress.stop()
                    self.btn_start.configure(state='normal')
                    port = extract_port(self.port_var.get())
                    if port:
                        self.app.start_reader(port)
        except queue.Empty:
            pass
        self.win.after(100, self._process_queue)

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno('Atualização em andamento', 'A gravação ainda está em andamento. Deseja fechar mesmo assim?'):
                return
            try:
                if self.proc and self.proc.poll() is None:
                    self.proc.terminate()
            except Exception:
                pass
        self.win.destroy()


# =========================================================
# AI ANALYZER WINDOW
# =========================================================
class AnalyzerDialog:
    def __init__(self, app: 'SerialApp'):
        self.app = app
        self.root = app.root
        self.settings = app.settings
        self.theme = app.theme
        self.running = False
        self.queue = queue.Queue()

        self.win = tk.Toplevel(self.root)
        self.win.title('Analisador de Log (IA)')
        self.win.geometry('780x560')
        self.win.minsize(720, 500)
        self.win.transient(self.root)
        self.win.grab_set()
        self.win.configure(bg=self.theme['bg'])

        self._build_ui()
        self._apply_theme()
        self._process_queue()
        self.win.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build_ui(self):
        outer = ttk.Frame(self.win, padding=14, style='App.TFrame')
        outer.pack(fill='both', expand=True)

        top = ttk.Frame(outer, style='Card.TFrame', padding=12)
        top.pack(fill='x')

        ttk.Label(top, text='Google Gemini API Key:', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        self.api_key_var = tk.StringVar(value=self.settings.get('ai_api_key', ''))
        self.api_key_entry = tk.Entry(top, textvariable=self.api_key_var, show='*')
        self.api_key_entry.grid(row=0, column=1, sticky='ew', padx=(8, 8), pady=4)

        ttk.Label(top, text='Tipo de Equipamento:', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        self.equip_var = tk.StringVar(value=self.settings.get('last_equip', 'RA24'))
        self.equip_combo = ttk.Combobox(top, textvariable=self.equip_var, values=['RA24', 'RA22', 'RA23', 'SENSOR DE COLISÃO', 'OUTROS'], state='normal')
        self.equip_combo.grid(row=1, column=1, sticky='ew', padx=(8, 8), pady=4)

        ttk.Label(top, text='Contexto / Problema:', style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.context_var = tk.StringVar()
        self.context_entry = tk.Entry(top, textvariable=self.context_var)
        self.context_entry.grid(row=2, column=1, sticky='ew', padx=(8, 8), pady=4)

        ttk.Label(top, text='Análise e Solução:', style='Card.TLabel', font=('Segoe UI', 11, 'bold')).grid(row=3, column=0, columnspan=2, sticky='w', pady=(10, 4))
        
        btn_frame = ttk.Frame(top, style='Card.TFrame')
        btn_frame.grid(row=4, column=0, columnspan=2, sticky='w', pady=(4, 0))
        
        self.btn_analyze = ttk.Button(btn_frame, text='Somente Analisar', command=lambda: self.start_analysis(resolve=False))
        self.btn_analyze.pack(side='left', padx=(0, 8))
        self.btn_resolve = ttk.Button(btn_frame, text='Analisar e Resolver (Sugerir Comando)', command=lambda: self.start_analysis(resolve=True))
        self.btn_resolve.pack(side='left')
        
        top.columnconfigure(1, weight=1)

        mid = ttk.Frame(outer, style='Card.TFrame', padding=10)
        mid.pack(fill='both', expand=True, pady=(12, 0))

        self.status_var = tk.StringVar(value='Pronto para iniciar.')
        ttk.Label(mid, textvariable=self.status_var, style='Card.TLabel').pack(anchor='w')

        self.progress = ttk.Progressbar(mid, mode='indeterminate')
        self.progress.pack(fill='x', pady=(8, 10))

        self.output = tk.Text(mid, wrap='word', relief='flat', borderwidth=0, font=('Segoe UI', 10))
        self.output.pack(fill='both', expand=True)
        self.scroll = ttk.Scrollbar(mid, orient='vertical', command=self.output.yview)
        self.scroll.pack(side='right', fill='y')
        self.output.configure(yscrollcommand=self.scroll.set)

    def _apply_theme(self):
        self.win.configure(bg=self.theme['bg'])
        self.output.configure(bg=self.theme['log_bg'], fg=self.theme['log_fg'], insertbackground=self.theme['log_fg'])
        self.api_key_entry.configure(bg=self.theme['entry_bg'], fg=self.theme['entry_fg'], insertbackground=self.theme['entry_fg'])
        self.context_entry.configure(bg=self.theme['entry_bg'], fg=self.theme['entry_fg'], insertbackground=self.theme['entry_fg'])

    def _set_output(self, text: str):
        self.output.configure(state='normal')
        self.output.delete('1.0', tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state='disabled')

    def start_analysis(self, resolve: bool):
        if self.running:
            return

        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning('Atenção', 'Por favor, insira sua chave de API do Gemini.')
            return

        self.settings['ai_api_key'] = api_key
        self.settings['last_equip'] = self.equip_var.get().strip()
        save_settings(self.settings)

        log_lines = self.app.log_buffer[-100:]
        if not log_lines:
            messagebox.showinfo('Informação', 'O log está vazio. Nada para analisar.')
            return
            
        log_text = '\n'.join(log_lines)

        self.running = True
        self.btn_analyze.configure(state='disabled')
        self.btn_resolve.configure(state='disabled')
        self.progress.start(12)
        self.status_var.set('Analisando log com IA... Aguarde.')
        self._set_output('Conectando ao Google Gemini...')

        threading.Thread(target=self._ai_worker, args=(api_key, log_text, resolve, self.equip_var.get().strip(), self.context_var.get().strip()), daemon=True).start()

    def _ai_worker(self, api_key: str, log_text: str, resolve: bool, equip: str, context: str):
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash-lite')
            
            ctx_str = f"Equipamento: {equip}\nContexto: {context}\n" if context else f"Equipamento: {equip}\n"
            base_instructions = "Seja extremamente direto, objetivo e técnico. Responda em tópicos curtos e sem enrolação ou textos de introdução.\n"
            
            if resolve:
                prompt = (
                    f"{base_instructions}\n"
                    "Você é um especialista em hardware. Analise o log serial abaixo.\n"
                    f"{ctx_str}\n"
                    "Descreva o problema de forma muito resumida.\n"
                    "Na ÚLTIMA LINHA da sua resposta, forneça APENAS O COMANDO EXATO a ser enviado pela porta serial para resolver o problema. Coloque o comando entre crases `comando`.\n\n"
                    "LOG:\n"
                    f"{log_text}"
                )
            else:
                prompt = (
                    f"{base_instructions}\n"
                    "Você é um especialista em hardware. Analise o log serial abaixo.\n"
                    f"{ctx_str}\n"
                    "Explique o que está acontecendo no log de forma muito resumida (1 ou 2 parágrafos no máximo).\n\n"
                    "LOG:\n"
                    f"{log_text}"
                )

            response = model.generate_content(prompt)
            result_text = response.text
            
            self.queue.put(('success', result_text, resolve))
        except ImportError:
            self.queue.put(('error', 'Biblioteca google-generativeai não está instalada.\nAbra o terminal e digite: pip install google-generativeai', False))
        except Exception as e:
            self.queue.put(('error', f'Erro ao chamar a IA:\n{e}', False))
        finally:
            self.queue.put(('done', None, None))

    def _process_queue(self):
        try:
            while True:
                kind, a, resolve = self.queue.get_nowait()
                if kind == 'success':
                    self._set_output(a)
                    self.status_var.set('Análise concluída com sucesso.')
                    if resolve:
                        import re
                        matches = re.findall(r'`([^`]+)`', a)
                        if matches:
                            cmd = matches[-1].strip()
                            self.app.widgets['cmd_var'].set(cmd)
                            messagebox.showinfo('Comando Sugerido', f'A IA sugeriu o comando:\n{cmd}\n\nO comando foi preenchido na caixa principal. Verifique e clique em "Enviar comando".')
                        else:
                            messagebox.showinfo('Comando Sugerido', 'A IA não forneceu um comando formatado entre crases.')
                elif kind == 'error':
                    self._set_output(a)
                    self.status_var.set('Erro na análise.')
                elif kind == 'done':
                    self.running = False
                    self.progress.stop()
                    self.btn_analyze.configure(state='normal')
                    self.btn_resolve.configure(state='normal')
        except queue.Empty:
            pass
        self.win.after(100, self._process_queue)

    def _on_close(self):
        self.win.destroy()


# =========================================================
# MAIN APP
# =========================================================
class SerialApp:
    def __init__(self):
        self.settings = load_settings()
        self.theme_name = self.settings.get('theme', 'dark') if self.settings.get('theme') in THEMES else 'dark'
        self.theme = THEMES[self.theme_name]

        self.root = tk.Tk()
        self.root.title('Leitor Serial Pro')
        self.root.geometry('1200x760')
        self.root.minsize(1060, 650)

        # --- Ícone da janela/taskbar ---
        try:
            import sys as _sys
            _media = (Path(_sys._MEIPASS) / 'media') if hasattr(_sys, '_MEIPASS') else (BASE_DIR / 'media')
            _ico = _media / 'ico.ico'
            _png = _media / 'logo.PNG'
            if _ico.exists():
                self.root.iconbitmap(str(_ico))
            if _png.exists():
                from PIL import Image as _Img, ImageTk as _ITk
                _img = _Img.open(str(_png)).convert('RGBA')
                _img.thumbnail((64, 64), _Img.LANCZOS)
                self._icon_photo = _ITk.PhotoImage(_img)
                self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        self.queue = queue.Queue()
        self.log_buffer = []
        self.reader_thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.serial_lock = threading.Lock()
        self.ser = None
        self.widgets = {}

        self._build_ui()
        self.apply_theme()
        self.refresh_ports(select_last=True)
        self.process_queue()
        self.root.after(700, self.auto_start_last_port)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def _build_ui(self):
        self.style.configure('App.TFrame', background=self.theme['bg'])
        self.style.configure('Card.TFrame', background=self.theme['card'])
        self.style.configure('App.TLabel', background=self.theme['bg'], foreground=self.theme['text'])
        self.style.configure('Card.TLabel', background=self.theme['card'], foreground=self.theme['text'])
        self.style.configure('Title.TLabel', background=self.theme['bg'], foreground=self.theme['text'], font=('Segoe UI', 17, 'bold'))
        self.style.configure('Muted.TLabel', background=self.theme['bg'], foreground=self.theme['muted'], font=('Segoe UI', 10))
        self.style.configure('TButton', font=('Segoe UI', 10), padding=7)
        self.style.configure(SMALL_BTN_STYLE, font=('Segoe UI', 8), padding=3)
        self.style.configure('TCheckbutton', background=self.theme['card'], foreground=self.theme['text'], font=('Segoe UI', 10))
        self.style.configure('TCombobox', padding=5)
        self.style.configure('TSpinbox', padding=5)

        main = ttk.Frame(self.root, padding=14, style='App.TFrame')
        main.pack(fill='both', expand=True)
        main.rowconfigure(1, weight=1)
        main.columnconfigure(1, weight=1)

        header = ttk.Frame(main, style='App.TFrame')
        header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        header.columnconfigure(1, weight=1)

        # Logo no header
        self._header_logo = None
        try:
            import sys as _sys
            from PIL import Image as _Img, ImageTk as _ITk
            _media = (Path(_sys._MEIPASS) / 'media') if hasattr(_sys, '_MEIPASS') else (BASE_DIR / 'media')
            _png = _media / 'logo.PNG'
            if _png.exists():
                _img = _Img.open(str(_png)).convert('RGBA')
                _img.thumbnail((56, 56), _Img.LANCZOS)
                self._header_logo = _ITk.PhotoImage(_img)
        except Exception:
            pass

        if self._header_logo:
            logo_lbl = tk.Label(header, image=self._header_logo, bg=self.theme['bg'])
            logo_lbl.grid(row=0, column=0, rowspan=2, sticky='w', padx=(0, 10))
            title_col = 1
        else:
            title_col = 0

        ttk.Label(header, text='Leitor Serial Pro', style='Title.TLabel').grid(row=0, column=title_col, sticky='w')
        ttk.Label(header, text='Controles na lateral e log ocupando toda a altura da tela.', style='Muted.TLabel').grid(row=1, column=title_col, sticky='w', pady=(4, 0))

        self.count_var = tk.StringVar(value='Linhas: 0')
        ttk.Label(header, textvariable=self.count_var, style='App.TLabel', font=('Segoe UI', 10, 'bold')).grid(row=0, column=title_col + 1, rowspan=2, sticky='e')

        sidebar = ttk.Frame(main, style='App.TFrame', width=360)
        sidebar.grid(row=1, column=0, sticky='nsw', padx=(0, 12))
        sidebar.grid_propagate(False)

        log_col = ttk.Frame(main, style='App.TFrame')
        log_col.grid(row=1, column=1, sticky='nsew')

        def card(parent, title):
            frame = ttk.Frame(parent, style='Card.TFrame', padding=10)
            frame.pack(fill='x', pady=(0, 10))
            ttk.Label(frame, text=title, style='Card.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 8))
            return frame

        # Connection
        c1 = card(sidebar, 'Conexão')
        r1 = ttk.Frame(c1, style='Card.TFrame')
        r1.pack(fill='x')
        ttk.Label(r1, text='Porta:', style='Card.TLabel').pack(side='left')
        self.widgets['combo_ports'] = ttk.Combobox(r1, state='readonly', width=30)
        self.widgets['combo_ports'].pack(side='left', padx=(8, 0), fill='x', expand=True)
        r2 = ttk.Frame(c1, style='Card.TFrame')
        r2.pack(fill='x', pady=(8, 0))
        self.widgets['btn_refresh'] = ttk.Button(r2, text='Atualizar', style=SMALL_BTN_STYLE, command=lambda: self.refresh_ports(True))
        self.widgets['btn_refresh'].pack(side='left')
        self.widgets['btn_start'] = ttk.Button(r2, text='Iniciar', command=self.start_reader)
        self.widgets['btn_start'].pack(side='left', padx=(8, 0))
        self.widgets['btn_stop'] = ttk.Button(r2, text='Parar', command=self.stop_reader, state='disabled')
        self.widgets['btn_stop'].pack(side='left', padx=(8, 0))
        self.widgets['btn_pause'] = ttk.Button(r2, text='Pausar', command=self.pause_resume, state='disabled')
        self.widgets['btn_pause'].pack(side='left', padx=(8, 0))

        # Log/save
        c2 = card(sidebar, 'Salvamento')
        self.widgets['auto_var'] = tk.BooleanVar(value=bool(self.settings.get('auto_save', True)))
        ttk.Checkbutton(c2, text='Salvar automaticamente', variable=self.widgets['auto_var']).pack(anchor='w', pady=(0, 6))
        r = ttk.Frame(c2, style='Card.TFrame')
        r.pack(fill='x')
        ttk.Label(r, text='Arquivo:', style='Card.TLabel').pack(side='left')
        self.widgets['entry_file'] = tk.Entry(r)
        self.widgets['entry_file'].pack(side='left', padx=(8, 0), fill='x', expand=True)
        self.widgets['entry_file'].insert(0, self.settings.get('log_file', str(DEFAULT_LOG_FILE)))
        r2 = ttk.Frame(c2, style='Card.TFrame')
        r2.pack(fill='x', pady=(8, 0))
        ttk.Button(r2, text='Escolher...', style=SMALL_BTN_STYLE, command=self.choose_log_file).pack(side='left')
        ttk.Button(r2, text='Salvar agora', style=SMALL_BTN_STYLE, command=self.save_log_manual).pack(side='left', padx=(6, 0))
        ttk.Button(r2, text='Limpar tela', style=SMALL_BTN_STYLE, command=self.clear_visible_log).pack(side='left', padx=(6, 0))
        ttk.Button(r2, text='Copiar log', style=SMALL_BTN_STYLE, command=self.copy_visible_log).pack(side='left', padx=(6, 0))

        # Command
        c3 = card(sidebar, 'Comando')
        ttk.Label(c3, text='Enviar comando ao rastreador:', style='Card.TLabel').pack(anchor='w')
        self.widgets['cmd_var'] = tk.StringVar(value=self.settings.get('last_command', ''))
        self.widgets['entry_cmd'] = tk.Entry(c3, textvariable=self.widgets['cmd_var'])
        self.widgets['entry_cmd'].pack(fill='x', pady=(4, 0))
        ttk.Button(c3, text='Enviar comando', command=self.send_command).pack(anchor='e', pady=(8, 0))

        # Firmware
        c4 = card(sidebar, 'Firmware')
        ttk.Button(c4, text='Gravar firmware', command=self.open_firmware_dialog).pack(anchor='w')

        # AI Analyzer
        c_ai = card(sidebar, 'IA')
        ttk.Button(c_ai, text='Analisador de Log (IA)', command=self.open_analyzer_dialog).pack(anchor='w')

        # Visual
        c5 = card(sidebar, 'Aparência')
        self.widgets['btn_theme'] = ttk.Button(c5, text='Tema claro' if self.theme_name == 'dark' else 'Tema escuro', style=SMALL_BTN_STYLE, command=self.toggle_theme)
        self.widgets['btn_theme'].pack(side='left')
        ttk.Button(c5, text='Personalização', style=SMALL_BTN_STYLE, command=self.open_personalization).pack(side='left', padx=(6, 0))
        ttk.Label(c5, text='A área de log não é editável.', style='Card.TLabel').pack(anchor='w', pady=(8, 0))

        # Main log
        log_top_frame = ttk.Frame(log_col, style='App.TFrame')
        log_top_frame.pack(fill='x', pady=(0, 5))
        ttk.Label(log_top_frame, text='Pesquisar no log:', style='Muted.TLabel').pack(side='left', padx=(0, 5))
        self.widgets['search_var'] = tk.StringVar()
        self.widgets['entry_search'] = tk.Entry(log_top_frame, textvariable=self.widgets['search_var'])
        self.widgets['entry_search'].pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.widgets['entry_search'].bind('<Return>', lambda e: self.search_log())
        ttk.Button(log_top_frame, text='Buscar', style=SMALL_BTN_STYLE, command=self.search_log).pack(side='left', padx=(0, 5))
        ttk.Button(log_top_frame, text='Limpar Busca', style=SMALL_BTN_STYLE, command=self.clear_search).pack(side='left')

        log_card = ttk.Frame(log_col, style='Card.TFrame', padding=10)
        log_card.pack(fill='both', expand=True)
        self.widgets['text_log'] = tk.Text(
            log_card,
            wrap='none',
            relief='flat',
            borderwidth=0,
            undo=False,
            state='disabled',
            font=(self.settings.get('font_family', 'Consolas'), int(self.settings.get('font_size', 10))),
        )
        self.widgets['text_log'].pack(side='left', fill='both', expand=True)
        yscroll = ttk.Scrollbar(log_card, orient='vertical', command=self.widgets['text_log'].yview)
        yscroll.pack(side='right', fill='y')
        self.widgets['text_log'].configure(yscrollcommand=yscroll.set)

        status_frame = ttk.Frame(main, style='App.TFrame')
        status_frame.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.widgets['status_var'] = tk.StringVar(value='Pronto para iniciar.')
        self.widgets['status_label'] = tk.Label(status_frame, textvariable=self.widgets['status_var'], anchor='w')
        self.widgets['status_label'].pack(anchor='w')

        # Additional control vars
        self.widgets['font_var'] = tk.StringVar(value=self.settings.get('font_family', 'Consolas'))
        self.widgets['size_var'] = tk.StringVar(value=str(self.settings.get('font_size', 10)))
        self.widgets['font_color_var'] = tk.StringVar(value=self.settings.get('font_color', ''))
        self.widgets['log_bg_var'] = tk.StringVar(value=self.settings.get('log_bg', ''))

    def apply_theme(self):
        self.theme = THEMES[self.theme_name]
        self.root.configure(bg=self.theme['bg'])
        self.style.configure('App.TFrame', background=self.theme['bg'])
        self.style.configure('Card.TFrame', background=self.theme['card'])
        self.style.configure('App.TLabel', background=self.theme['bg'], foreground=self.theme['text'])
        self.style.configure('Card.TLabel', background=self.theme['card'], foreground=self.theme['text'])
        self.style.configure('Title.TLabel', background=self.theme['bg'], foreground=self.theme['text'], font=('Segoe UI', 17, 'bold'))
        self.style.configure('Muted.TLabel', background=self.theme['bg'], foreground=self.theme['muted'], font=('Segoe UI', 10))
        self.style.configure('TCheckbutton', background=self.theme['card'], foreground=self.theme['text'], font=('Segoe UI', 10))
        self.widgets['entry_file'].configure(bg=self.theme['entry_bg'], fg=self.theme['entry_fg'], insertbackground=self.theme['entry_fg'])
        self.widgets['entry_cmd'].configure(bg=self.theme['entry_bg'], fg=self.theme['entry_fg'], insertbackground=self.theme['entry_fg'])
        self.widgets['entry_search'].configure(bg=self.theme['entry_bg'], fg=self.theme['entry_fg'], insertbackground=self.theme['entry_fg'])
        self.widgets['text_log'].configure(bg=self.theme['log_bg'], fg=self.theme['log_fg'], insertbackground=self.theme['log_fg'])
        self.widgets['text_log'].tag_configure('normal', foreground=self.theme['log_fg'])
        self.widgets['text_log'].tag_configure('error', foreground=self.theme['error'])
        self.widgets['text_log'].tag_configure('info', foreground=self.theme['info'])
        self.widgets['text_log'].tag_configure('success', foreground=self.theme['success'])
        self.widgets['text_log'].tag_configure('warning', foreground=self.theme['warning'])
        self.widgets['text_log'].tag_configure('search', background='#eab308', foreground='#000000')
        self.widgets['status_label'].configure(bg=self.theme['bg'], fg=self.theme['text'])
        self.widgets['btn_theme'].configure(text='Tema claro' if self.theme_name == 'dark' else 'Tema escuro')

    def toggle_theme(self):
        self.theme_name = 'light' if self.theme_name == 'dark' else 'dark'
        self.settings['theme'] = self.theme_name
        save_settings(self.settings)
        self.apply_theme()
        self.update_status(f'Tema {self.theme_name} ativado.', self.theme['success'])

    def set_status(self, text: str, color: str | None = None):
        self.widgets['status_var'].set(text)
        if color:
            self.widgets['status_label'].configure(fg=color)

    def update_status(self, text: str, color: str | None = None):
        self.set_status(text, color)

    def search_log(self):
        text_widget = self.widgets['text_log']
        text_widget.tag_remove('search', '1.0', tk.END)
        query = self.widgets['search_var'].get()
        if not query:
            return
        
        pos = '1.0'
        first_match = None
        count = 0
        while True:
            pos = text_widget.search(query, pos, stopindex=tk.END, nocase=True)
            if not pos:
                break
            if not first_match:
                first_match = pos
            count += 1
            end_pos = f'{pos}+{len(query)}c'
            text_widget.tag_add('search', pos, end_pos)
            pos = end_pos
            
        if count > 0:
            text_widget.see(first_match)
            self.update_status(f"Busca: '{query}' ({count} ocorrências).", self.theme['success'])
        else:
            self.update_status(f"Busca: '{query}' não encontrado.", self.theme['warning'])

    def clear_search(self):
        self.widgets['search_var'].set('')
        self.widgets['text_log'].tag_remove('search', '1.0', tk.END)
        self.update_status('Busca limpa.', self.theme['info'])

    def update_status_threadsafe(self, text: str, color: str | None = None):
        self.queue.put(('status', text, color))

    def append_log_line(self, line: str, tag: str | None = None):
        if tag is None:
            tag = 'error' if is_error_line(line) else 'normal'
        text = self.widgets['text_log']
        text.configure(state='normal')
        text.insert(tk.END, line + '\n', tag)
        text.see(tk.END)
        text.configure(state='disabled')

    def write_log_line(self, line: str, tag: str | None = None):
        self.log_buffer.append(line)
        self.append_log_line(line, tag=tag)
        self.count_var.set(f'Linhas: {len(self.log_buffer)}')
        if self.widgets['auto_var'].get():
            path = self.widgets['entry_file'].get().strip() or str(DEFAULT_LOG_FILE)
            try:
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception as e:
                self.update_status(f'Falha ao salvar automaticamente: {e}', self.theme['error'])

    def clear_visible_log(self):
        try:
            self.widgets['text_log'].configure(state='normal')
            self.widgets['text_log'].delete('1.0', tk.END)
            self.widgets['text_log'].configure(state='disabled')
            self.log_buffer.clear()
            self.count_var.set('Linhas: 0')
            self.update_status('Tela limpa. Histórico em memória também foi zerado.', self.theme['warning'])
        except Exception as e:
            safe_messagebox_error('Erro', f'Não foi possível limpar a tela: {e}')

    def copy_visible_log(self):
        try:
            text = self.widgets['text_log'].get('1.0', tk.END).strip()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self.update_status('Log copiado.', self.theme['success'])
        except Exception as e:
            safe_messagebox_error('Erro', f'Não foi possível copiar o log: {e}')

    def choose_log_file(self):
        path = filedialog.asksaveasfilename(
            title='Salvar log como',
            defaultextension='.txt',
            filetypes=[('Arquivo de texto', '*.txt'), ('Todos os arquivos', '*.*')],
            initialfile=Path(self.widgets['entry_file'].get().strip() or str(DEFAULT_LOG_FILE)).name,
        )
        if path:
            self.widgets['entry_file'].delete(0, tk.END)
            self.widgets['entry_file'].insert(0, path)
            self.settings['log_file'] = path
            save_settings(self.settings)

    def save_log_manual(self):
        try:
            path = self.widgets['entry_file'].get().strip()
            if not path:
                raise ValueError('Informe um arquivo para salvar.')
            with open(path, 'w', encoding='utf-8') as f:
                for line in self.log_buffer:
                    f.write(line + '\n')
            self.settings['log_file'] = path
            self.settings['auto_save'] = self.widgets['auto_var'].get()
            save_settings(self.settings)
            self.update_status(f'Log salvo em {path}', self.theme['success'])
        except Exception as e:
            messagebox.showerror('Erro ao salvar', str(e))

    def apply_log_style(self):
        try:
            fam = self.widgets['font_var'].get().strip() or 'Consolas'
            size = int(self.widgets['size_var'].get())
            self.widgets['text_log'].configure(font=(fam, size))
        except Exception:
            pass
        try:
            fg = self.widgets['font_color_var'].get().strip()
            bg = self.widgets['log_bg_var'].get().strip()
            if fg:
                self.widgets['text_log'].configure(fg=fg)
                self.widgets['text_log'].tag_configure('normal', foreground=fg)
            if bg:
                self.widgets['text_log'].configure(bg=bg)
        except Exception:
            pass

    def open_personalization(self):
        win = tk.Toplevel(self.root)
        win.title('Personalização do log')
        win.geometry('360x180')
        win.resizable(False, False)
        win.configure(bg=self.theme['bg'])
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=12, style='Card.TFrame')
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text='Fonte', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        ttk.Combobox(frm, textvariable=self.widgets['font_var'], values=sorted(set(tkfont.families(self.root))), width=24).grid(row=0, column=1, sticky='ew', pady=4)
        ttk.Label(frm, text='Tamanho', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        ttk.Spinbox(frm, from_=8, to=24, textvariable=self.widgets['size_var'], width=8).grid(row=1, column=1, sticky='w', pady=4)
        ttk.Button(frm, text='Cor da fonte', style=SMALL_BTN_STYLE, command=lambda: self.choose_color('font_color_var')).grid(row=2, column=0, sticky='ew', pady=(10, 4))
        ttk.Button(frm, text='Cor de fundo', style=SMALL_BTN_STYLE, command=lambda: self.choose_color('log_bg_var')).grid(row=2, column=1, sticky='ew', pady=(10, 4))
        ttk.Button(frm, text='Aplicar', command=lambda: self.finish_personalization(win)).grid(row=3, column=1, sticky='e', pady=(12, 0))
        frm.columnconfigure(1, weight=1)

    def choose_color(self, var_name: str):
        c = colorchooser.askcolor(title='Escolher cor')
        if c and c[1]:
            self.widgets[var_name].set(c[1])

    def finish_personalization(self, win):
        try:
            self.settings['font_family'] = self.widgets['font_var'].get().strip() or 'Consolas'
            try:
                self.settings['font_size'] = int(self.widgets['size_var'].get())
            except Exception:
                self.settings['font_size'] = 10
            self.settings['font_color'] = self.widgets['font_color_var'].get().strip()
            self.settings['log_bg'] = self.widgets['log_bg_var'].get().strip()
            save_settings(self.settings)
            self.apply_log_style()
            self.update_status('Personalização aplicada.', self.theme['success'])
            win.destroy()
        except Exception as e:
            messagebox.showerror('Erro', str(e))

    def is_reader_running(self) -> bool:
        return bool(self.reader_thread and self.reader_thread.is_alive() and not self.stop_event.is_set())

    def _open_serial(self, port: str) -> serial.Serial:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = BAUDRATE
        ser.timeout = TIMEOUT
        ser.dtr = False
        ser.rts = False
        ser.open()
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        return ser

    def reader_worker(self, port: str):
        while not self.stop_event.is_set():
            try:
                self.update_status_threadsafe(f'Conectando em {port}...', self.theme['muted'])
                with self.serial_lock:
                    self.ser = self._open_serial(port)
                self.update_status_threadsafe(f'Conectado em {port}', self.theme['success'])

                while not self.stop_event.is_set() and self.ser and self.ser.is_open:
                    if self.pause_event.is_set():
                        time.sleep(0.05)
                        continue

                    try:
                        with self.serial_lock:
                            raw = self.ser.readline().decode(errors='ignore').strip()
                        raw = strip_ansi(raw)
                        if raw:
                            self.queue.put(('log', f'{now_str()} - {raw}', None))
                    except (serial.SerialException, OSError) as e:
                        self.queue.put(('status', f'Conexão perdida: {e}', self.theme['error']))
                        break
                    except Exception as e:
                        self.queue.put(('status', f'Erro de leitura: {e}', self.theme['error']))
                        break

            except serial.SerialException as e:
                self.update_status_threadsafe(f'Falha ao conectar: {e}', self.theme['error'])
                time.sleep(RETRY_DELAY)
            except Exception as e:
                self.update_status_threadsafe(f'Erro inesperado: {e}', self.theme['error'])
                time.sleep(RETRY_DELAY)
            finally:
                try:
                    if self.ser and self.ser.is_open:
                        self.ser.close()
                except Exception:
                    pass

                if not self.stop_event.is_set():
                    self.update_status_threadsafe(f'Tentando reconectar em {RETRY_DELAY}s...', self.theme['warning'])
                    time.sleep(RETRY_DELAY)

        self.update_status_threadsafe('Leitura parada.', self.theme['muted'])

    def refresh_ports(self, select_last: bool = True):
        ports = list_serial_ports()
        self.widgets['combo_ports']['values'] = ports
        selected = ''
        last = self.settings.get('last_port', '').strip()
        if select_last and last:
            for item in ports:
                if extract_port(item) == last:
                    selected = item
                    break
        if selected:
            self.widgets['combo_ports'].set(selected)
        elif ports:
            self.widgets['combo_ports'].current(0)
        else:
            self.widgets['combo_ports'].set('')
        self.update_status('Portas atualizadas.', self.theme['success'] if ports else self.theme['warning'])

    def selected_port(self) -> str:
        return extract_port(self.widgets['combo_ports'].get())

    def start_reader(self, port_override: str | None = None):
        if self.is_reader_running():
            messagebox.showinfo('Informação', 'A leitura já está em execução.')
            return
        port = port_override or self.selected_port()
        if not port:
            messagebox.showwarning('Atenção', 'Selecione uma porta serial disponível.')
            return
        self.settings['last_port'] = port
        self.settings['theme'] = self.theme_name
        self.settings['auto_save'] = self.widgets['auto_var'].get()
        self.settings['log_file'] = self.widgets['entry_file'].get().strip() or str(DEFAULT_LOG_FILE)
        save_settings(self.settings)
        self.stop_event.clear()
        self.pause_event.clear()
        self.widgets['btn_pause'].configure(text='Pausar')
        self.reader_thread = threading.Thread(target=self.reader_worker, args=(port,), daemon=True)
        self.reader_thread.start()
        self.widgets['btn_start'].configure(state='disabled')
        self.widgets['btn_stop'].configure(state='normal')
        self.widgets['btn_pause'].configure(state='normal')
        self.update_status(f'Iniciando leitura em {port}...', self.theme['success'])

    def stop_reader(self, wait: bool = False):
        self.stop_event.set()
        self.pause_event.clear()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        if wait and self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2.0)
        self.widgets['btn_start'].configure(state='normal')
        self.widgets['btn_stop'].configure(state='disabled')
        self.widgets['btn_pause'].configure(state='disabled', text='Pausar')

    def pause_resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.widgets['btn_pause'].configure(text='Pausar')
            self.update_status('Leitura retomada.', self.theme['success'])
        else:
            self.pause_event.set()
            self.widgets['btn_pause'].configure(text='Retomar')
            self.update_status('Leitura pausada.', self.theme['warning'])

    def auto_start_last_port(self):
        try:
            last_port = self.settings.get('last_port', '').strip()
            if not last_port:
                return
            for item in list_serial_ports():
                if extract_port(item) == last_port:
                    self.widgets['combo_ports'].set(item)
                    self.start_reader(port_override=last_port)
                    return
            self.update_status(f'Última porta usada ({last_port}) não está disponível.', self.theme['warning'])
        except Exception as e:
            self.update_status(f'Auto-início falhou: {e}', self.theme['error'])

    def send_command(self):
        port = self.selected_port()
        cmd = self.widgets['cmd_var'].get().strip()
        if not port:
            messagebox.showwarning('Atenção', 'Selecione uma porta serial.')
            return
        if not cmd:
            messagebox.showwarning('Atenção', 'Digite um comando para enviar.')
            return

        was_running = self.is_reader_running()
        if was_running:
            self.pause_event.set()
            time.sleep(0.1)

        self.settings['last_command'] = cmd
        save_settings(self.settings)
        threading.Thread(target=self._send_command_worker, args=(port, cmd, was_running), daemon=True).start()

    def _send_command_worker(self, port: str, cmd: str, resume_reader: bool):
        temp_ser = None
        try:
            self.queue.put(('log', f'{now_str()} - COMANDO ENVIANDO: {cmd}', 'info'))
            self.update_status_threadsafe('Enviando comando...', self.theme['muted'])

            with self.serial_lock:
                if self.ser and self.ser.is_open:
                    ser_obj = self.ser
                    local = False
                else:
                    ser_obj = self._open_serial(port)
                    local = True
                    temp_ser = ser_obj

                try:
                    ser_obj.reset_input_buffer()
                    ser_obj.write((cmd + '\r\n').encode('utf-8'))
                    ser_obj.flush()
                except Exception:
                    pass

            response_end = time.time() + 1.3
            while time.time() < response_end:
                with self.serial_lock:
                    ser_obj = self.ser if self.ser and self.ser.is_open else temp_ser
                    if not ser_obj:
                        break
                    try:
                        line = ser_obj.readline().decode(errors='ignore').strip()
                    except Exception:
                        line = ''
                line = strip_ansi(line)
                if line:
                    self.queue.put(('log', f'{now_str()} - {line}', None))
                else:
                    time.sleep(0.05)

            self.update_status_threadsafe('Comando enviado.', self.theme['success'])
        except Exception as e:
            self.update_status_threadsafe(f'Erro ao enviar comando: {e}', self.theme['error'])
            self.queue.put(('log', f'{now_str()} - [ERRO] {e}', 'error'))
        finally:
            try:
                if temp_ser and temp_ser.is_open:
                    temp_ser.close()
            except Exception:
                pass
            if resume_reader:
                self.pause_event.clear()

    def open_firmware_dialog(self):
        FirmwareDialog(self)

    def open_analyzer_dialog(self):
        AnalyzerDialog(self)

    def process_queue(self):
        try:
            while True:
                kind, a, b = self.queue.get_nowait()
                if kind == 'log':
                    self.write_log_line(a, tag=b)
                elif kind == 'status':
                    self.set_status(a, b)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def on_close(self):
        try:
            self.settings['theme'] = self.theme_name
            self.settings['auto_save'] = self.widgets['auto_var'].get()
            self.settings['log_file'] = self.widgets['entry_file'].get().strip() or str(DEFAULT_LOG_FILE)
            self.settings['last_command'] = self.widgets['cmd_var'].get().strip()
            save_settings(self.settings)
        except Exception:
            pass

        if not self.widgets['auto_var'].get() and self.log_buffer:
            try:
                if messagebox.askyesno('Salvar log', 'O salvamento automático está desligado. Deseja salvar o log antes de sair?'):
                    self.save_log_manual()
            except Exception:
                pass

        self.stop_reader(wait=False)
        self.root.after(150, self.root.destroy)

    def run(self):
        self.root.mainloop()


# =========================================================
# MAIN
# =========================================================
def main():
    app = SerialApp()
    app.apply_theme()
    app.apply_log_style()
    app.run()


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
