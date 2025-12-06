import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
import os
import threading
import queue
import multiprocessing
import sys

from raw_alchemy import core, orchestrator
from raw_alchemy.orchestrator import SUPPORTED_RAW_EXTENSIONS

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class GuiApplication(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.master.title("Raw Alchemy")
        self.master.geometry("1000x900")
        
        # Set Icon
        try:
            # For Windows, iconbitmap is the standard way to set the window icon from an .ico file.
            icon_path = resource_path("icon.ico")
            self.master.iconbitmap(icon_path)
        except Exception as e:
            print(f"Error loading window icon: {e}")

        self.pack(fill="both", expand=True)
        self.create_widgets()
        self.log_queue = queue.Queue()
        self.master.after(100, self.process_log_queue)

    def create_widgets(self):
        # --- Frame for IO ---
        io_frame = ttk.LabelFrame(self, text="Input/Output", padding=(10, 5))
        io_frame.pack(padx=10, pady=5, fill="x")

        # Input path
        self.input_path_label = ttk.Label(io_frame, text="Input Path:")
        self.input_path_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.input_path_var = tk.StringVar()
        self.input_path_entry = ttk.Entry(io_frame, textvariable=self.input_path_var, width=60)
        self.input_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        input_btn_frame = ttk.Frame(io_frame)
        input_btn_frame.grid(row=0, column=2, padx=5, pady=5)
        self.browse_input_file_btn = ttk.Button(input_btn_frame, text="Select File...", command=self.browse_input_file)
        self.browse_input_file_btn.pack(side="left", padx=(0, 2))
        self.browse_input_folder_btn = ttk.Button(input_btn_frame, text="Select Folder...", command=self.browse_input_folder)
        self.browse_input_folder_btn.pack(side="left")

        # Output path
        self.output_path_label = ttk.Label(io_frame, text="Output Path:")
        self.output_path_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.output_path_var = tk.StringVar()
        self.output_path_entry = ttk.Entry(io_frame, textvariable=self.output_path_var, width=60)
        self.output_path_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        output_btn_frame = ttk.Frame(io_frame)
        output_btn_frame.grid(row=1, column=2, padx=5, pady=5)
        self.browse_output_file_btn = ttk.Button(output_btn_frame, text="Save As...", command=self.browse_output_file)
        self.browse_output_file_btn.pack(side="left", padx=(0, 2))
        self.browse_output_folder_btn = ttk.Button(output_btn_frame, text="Select Folder...", command=self.browse_output_folder)
        self.browse_output_folder_btn.pack(side="left")
        
        io_frame.columnconfigure(1, weight=1)

        # --- Frame for Settings ---
        settings_frame = ttk.LabelFrame(self, text="Processing Settings", padding=(10, 5))
        settings_frame.pack(padx=10, pady=5, fill="x")

        # Log space
        self.log_space_label = ttk.Label(settings_frame, text="Log Space:")
        self.log_space_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.log_space_var = tk.StringVar(value=list(core.LOG_TO_WORKING_SPACE.keys())[0])
        self.log_space_menu = ttk.OptionMenu(settings_frame, self.log_space_var, self.log_space_var.get(), *core.LOG_TO_WORKING_SPACE.keys())
        self.log_space_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # LUT file
        self.lut_label = ttk.Label(settings_frame, text="LUT File (.cube):")
        self.lut_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.lut_path_var = tk.StringVar()
        self.lut_entry = ttk.Entry(settings_frame, textvariable=self.lut_path_var, width=60)
        self.lut_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.browse_lut_btn = ttk.Button(settings_frame, text="Browse...", command=self.browse_lut)
        self.browse_lut_btn.grid(row=1, column=2, padx=5, pady=5)

        # Custom Lensfun DB
        self.lensfun_db_label = ttk.Label(settings_frame, text="Custom Lensfun DB (XML):")
        self.lensfun_db_label.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.custom_lensfun_db_path_var = tk.StringVar()
        self.lensfun_db_entry = ttk.Entry(settings_frame, textvariable=self.custom_lensfun_db_path_var, width=60)
        self.lensfun_db_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        self.browse_lensfun_db_btn = ttk.Button(settings_frame, text="Browse...", command=self.browse_lensfun_db)
        self.browse_lensfun_db_btn.grid(row=2, column=2, padx=5, pady=5)

        # Concurrent Jobs
        self.jobs_label = ttk.Label(settings_frame, text="Concurrent Jobs:")
        self.jobs_label.grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.jobs_var = tk.IntVar(value=4)
        # Use cpu_count to set a reasonable max, default to 8 if it fails
        try:
            max_jobs = multiprocessing.cpu_count()
        except NotImplementedError:
            max_jobs = 8
        self.jobs_spinbox = ttk.Spinbox(settings_frame, from_=1, to=max_jobs, textvariable=self.jobs_var, width=10)
        self.jobs_spinbox.grid(row=3, column=1, padx=5, pady=5, sticky="w")

        settings_frame.columnconfigure(1, weight=1)

        # --- Frame for Exposure Settings ---
        exp_frame = ttk.LabelFrame(self, text="Exposure", padding=(10, 5))
        exp_frame.pack(padx=10, pady=5, fill="x")

        self.exposure_mode_var = tk.StringVar(value="Auto")
        
        # Radio buttons for mode selection
        auto_radio = ttk.Radiobutton(exp_frame, text="Auto", variable=self.exposure_mode_var, value="Auto", command=self.toggle_exposure_controls)
        auto_radio.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        
        manual_radio = ttk.Radiobutton(exp_frame, text="Manual", variable=self.exposure_mode_var, value="Manual", command=self.toggle_exposure_controls)
        manual_radio.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        # --- Auto exposure controls ---
        self.auto_exp_frame = ttk.Frame(exp_frame)
        self.auto_exp_frame.grid(row=0, column=1, padx=5, pady=0, sticky="ew")
        
        self.metering_mode_label = ttk.Label(self.auto_exp_frame, text="Metering:")
        self.metering_mode_label.pack(side="left", padx=(10, 5))
        
        self.metering_mode_var = tk.StringVar(value=core.METERING_MODES[3]) # Default to 'hybrid'
        self.metering_mode_menu = ttk.OptionMenu(self.auto_exp_frame, self.metering_mode_var, self.metering_mode_var.get(), *core.METERING_MODES)
        self.metering_mode_menu.pack(side="left", fill="x", expand=True)

        # --- Manual exposure controls ---
        self.manual_exp_frame = ttk.Frame(exp_frame)
        self.manual_exp_frame.grid(row=1, column=1, padx=5, pady=0, sticky="ew")
        
        self.exposure_stops_label = ttk.Label(self.manual_exp_frame, text="EV Stops:")
        self.exposure_stops_label.pack(side="left", padx=(10, 5))
        
        self.exposure_stops_var = tk.DoubleVar(value=0.0)
        self.exposure_stops_entry = ttk.Entry(self.manual_exp_frame, textvariable=self.exposure_stops_var, width=8)
        self.exposure_stops_entry.pack(side="left", padx=5)
        
        self.exposure_slider = ttk.Scale(self.manual_exp_frame, from_=-5.0, to=5.0, orient="horizontal", variable=self.exposure_stops_var, command=lambda v: self.exposure_stops_var.set(round(float(v), 2)))
        self.exposure_slider.pack(side="left", fill="x", expand=True)

        exp_frame.columnconfigure(1, weight=1)
        self.toggle_exposure_controls() # Set initial state

        # --- Frame for Log ---
        log_frame = ttk.LabelFrame(self, text="Log", padding=(10, 5))
        log_frame.pack(padx=10, pady=5, fill="both", expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        # --- Frame for Actions ---
        action_frame = ttk.Frame(self, padding=(10, 5))
        action_frame.pack(padx=10, pady=5, fill="x")

        self.start_button = ttk.Button(action_frame, text="Start Processing", command=self.start_processing_thread)
        self.start_button.pack(side="right")

    def toggle_exposure_controls(self):
        mode = self.exposure_mode_var.get()
        if mode == "Auto":
            for child in self.auto_exp_frame.winfo_children():
                child.config(state="normal")
            for child in self.manual_exp_frame.winfo_children():
                child.config(state="disabled")
        else: # Manual
            for child in self.auto_exp_frame.winfo_children():
                child.config(state="disabled")
            for child in self.manual_exp_frame.winfo_children():
                child.config(state="normal")

    def browse_input_file(self):
        # Create a file type string from the supported extensions, including both lower and upper case
        # to ensure compatibility with case-sensitive file systems like Linux.
        ext_patterns = " ".join(f"*{ext} *{ext.upper()}" for ext in SUPPORTED_RAW_EXTENSIONS)
        file_types = [("RAW files", ext_patterns), ("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=file_types)
        if path:
            self.input_path_var.set(path)

    def browse_input_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.input_path_var.set(path)

    def browse_output_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".tif", filetypes=[("TIFF files", "*.tif")])
        if path:
            self.output_path_var.set(path)

    def browse_output_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.output_path_var.set(path)

    def browse_lut(self):
        path = filedialog.askopenfilename(filetypes=[("CUBE files", "*.cube")])
        if path:
            self.lut_path_var.set(path)

    def browse_lensfun_db(self):
        path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if path:
            self.custom_lensfun_db_path_var.set(path)

    def log(self, message):
        self.log_queue.put(message)

    def process_log_queue(self):
        try:
            while True:
                log_item = self.log_queue.get_nowait()
                
                # 根据日志类型格式化消息
                if isinstance(log_item, dict):
                    # 结构化日志: {'id': filename, 'msg': message}
                    message = f"[{log_item['id']}] {log_item['msg']}"
                else:
                    # 普通字符串日志
                    message = str(log_item)

                self.log_text.config(state="normal")
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.master.after(100, self.process_log_queue)

    def start_processing_thread(self):
        self.start_button.config(state="disabled")
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
        
        thread = threading.Thread(target=self.run_processing)
        thread.daemon = True
        thread.start()

    def run_processing(self):
        input_path = self.input_path_var.get()
        output_path = self.output_path_var.get()
        log_space = self.log_space_var.get()
        lut_path = self.lut_path_var.get() or None
        custom_lensfun_db_path = self.custom_lensfun_db_path_var.get() or None
        jobs = self.jobs_var.get()
        
        # Get exposure settings from UI
        exposure_mode = self.exposure_mode_var.get()
        if exposure_mode == "Auto":
            exposure_val = None
            metering_mode = self.metering_mode_var.get()
        else: # Manual
            exposure_val = self.exposure_stops_var.get()
            metering_mode = None # Not used in manual mode

        if not input_path or not output_path:
            self.log("❌ Error: Input and Output paths must be selected.")
            self.master.after(100, lambda: self.start_button.config(state="normal"))
            return

        self.log(f"🎬 Starting processing...")
        self.log(f"  Input: {input_path}")
        self.log(f"  Output: {output_path}")
        self.log(f"  Settings: Log={log_space}, LUT={lut_path or 'None'}, Exposure={exposure_mode}")
        self.log(f"  Custom Lensfun DB: {custom_lensfun_db_path or 'Default'}")
        if exposure_mode == "Auto":
            self.log(f"    Metering Mode: {metering_mode}")
        else:
            self.log(f"    Exposure Stops: {exposure_val:+.2f} EV")

        # Use a multiprocessing manager queue for inter-process communication
        manager = multiprocessing.Manager()
        log_queue = manager.Queue()
        self.log_queue = log_queue

        try:
            orchestrator.process_path(
                input_path=input_path,
                output_path=output_path,
                log_space=log_space,
                lut_path=lut_path,
                exposure=exposure_val,
                lens_correct=True,
                custom_db_path=custom_lensfun_db_path,
                metering_mode=metering_mode,
                jobs=jobs,
                logger_func=self.log_queue, # Pass the queue directly
            )
        except Exception as e:
            self.log(f"  ❌ An unexpected error occurred: {e}")
        finally:
            # Re-enable button on the main thread
            self.master.after(100, lambda: self.start_button.config(state="normal"))


def launch_gui():
    # This is essential for multiprocessing to work correctly in a frozen app
    multiprocessing.freeze_support()
    
    root = tk.Tk()
    app = GuiApplication(master=root)
    app.mainloop()

if __name__ == "__main__":
    launch_gui()