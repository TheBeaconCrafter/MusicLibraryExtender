import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import requests
from PIL import Image, ImageTk
from io import BytesIO
import tempfile
import time
import shutil
import configparser
import yt_dlp
import html
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON, USLT, TRCK
import musicbrainzngs
import argparse
import sys
import json
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TaskID

class ArtworkSelectorDialog(tk.Toplevel):
    def __init__(self, parent, artwork_list):
        """Dialog for selecting from multiple artwork options"""
        super().__init__(parent)
        self.title("Select Cover Artwork")
        self.geometry("600x500")
        self.minsize(600, 500)
        self.transient(parent)
        self.grab_set()
        
        self.configure(bg="#2E3440")
        
        # Store artwork options
        self.artwork_list = artwork_list
        self.selected_index = None
        self.artwork_images = []  # Keep references to prevent garbage collection
        
        self.create_widgets()
        self.update_idletasks()
        self.center_window()
        
    def create_widgets(self):
        header_label = ttk.Label(self, text="Select cover artwork:", font=("Arial", 12, "bold"))
        header_label.pack(pady=(15, 10))
        
        gallery_frame = ttk.Frame(self)
        gallery_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        
        self.canvas = tk.Canvas(gallery_frame, bg="#2E3440", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(gallery_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.tiles_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.tiles_frame, anchor='nw')
        
        self.tiles_frame.bind("<Configure>", self.on_frame_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        
        if not self.artwork_list:
            no_art_label = ttk.Label(self.tiles_frame, text="No artwork options available", font=("Arial", 12))
            no_art_label.pack(pady=20)
        else:
            for i, artwork_data in enumerate(self.artwork_list):
                self.add_artwork_tile(i, artwork_data)
        
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=15, pady=15)
        
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.cancel)
        cancel_button.pack(side=tk.RIGHT, padx=5)
    
    def on_frame_configure(self, event):
        """Reset the scroll region to encompass the inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def on_canvas_configure(self, event):
        """Resize the inner frame to match the canvas"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        
    def add_artwork_tile(self, index, artwork_data):
        tile_frame = ttk.Frame(self.tiles_frame)
        tile_frame.pack(fill=tk.X, pady=10)
        
        try:
            img_data = BytesIO(artwork_data["data"])
            img = Image.open(img_data)
            
            img.thumbnail((180, 180), Image.Resampling.LANCZOS)
            
            photo_img = ImageTk.PhotoImage(img)
            self.artwork_images.append(photo_img)
            
            img_label = ttk.Label(tile_frame, image=photo_img)
            img_label.image = photo_img
            img_label.pack(side=tk.LEFT, padx=10)
            
            img_label.bind("<Button-1>", lambda e, idx=index: self.select_artwork(idx))
            
            info_frame = ttk.Frame(tile_frame)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            source_label = ttk.Label(info_frame, text=f"Source: {artwork_data['source']}", font=("Arial", 11))
            source_label.pack(anchor=tk.W, pady=(10, 0))
            
            size_label = ttk.Label(info_frame, text=f"Size: {len(artwork_data['data']) // 1024} KB", font=("Arial", 11))
            size_label.pack(anchor=tk.W)
            
            resolution = self.get_image_resolution(img)
            res_label = ttk.Label(info_frame, text=f"Resolution: {resolution[0]}x{resolution[1]}", font=("Arial", 11))
            res_label.pack(anchor=tk.W)
            
            select_button = ttk.Button(info_frame, text="Select", command=lambda idx=index: self.select_artwork(idx))
            select_button.pack(anchor=tk.W, pady=(10, 0))
            
            print(f"Added artwork tile {index}: {artwork_data['source']}, {resolution}")
            
        except Exception as e:
            print(f"Error creating artwork tile: {str(e)}")
            error_label = ttk.Label(tile_frame, text=f"Error loading image: {str(e)}")
            error_label.pack(side=tk.LEFT, padx=10)
    
    def get_image_resolution(self, img):
        """Get image width and height"""
        return img.size
    
    def select_artwork(self, index):
        """Handle artwork selection"""
        self.selected_index = index
        self.destroy()
    
    def cancel(self):
        """Handle cancel button"""
        self.selected_index = None
        self.destroy()
    
    def center_window(self):
        """Center the dialog on the parent window"""
        parent = self.master
        
        x = parent.winfo_x()
        y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        dialog_width = self.winfo_width()
        dialog_height = self.winfo_height()
        
        position_x = x + (parent_width - dialog_width) // 2
        position_y = y + (parent_height - dialog_height) // 2
        
        self.geometry(f"+{position_x}+{position_y}")

class MusicLibraryExtender:
    def __init__(self, root):
        self.root = root
        self.root.title("Music Library Extender")
        self.root.geometry("1300x920")
        self.root.minsize(900, 650)
        
        # Initialize MusicBrainz API for metadata
        musicbrainzngs.set_useragent("MusicLibraryExtender", "1.0.0", "https://github.com/TheBeaconCrafter/MusicLibraryExtender")
        
        self.set_theme()
        
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        
        self.load_settings()
        
        self.search_results = []
        self.selected_video = None
        self.thumbnail_image = None  # Keep reference to prevent garbage collection
        
        self.artwork_options = []
        
        self.create_widgets()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def load_settings(self):
        """Load settings from the config file or use defaults"""
        self.config = configparser.ConfigParser()
        
        self.library_location = os.path.join(os.path.expanduser("~"), "Music")
        
        if os.path.exists(self.config_file):
            try:
                self.config.read(self.config_file)
                if 'Settings' in self.config:
                    if 'library_location' in self.config['Settings']:
                        saved_path = self.config['Settings']['library_location']
                        if os.path.exists(saved_path):
                            self.library_location = saved_path
            except Exception as e:
                print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to the config file"""
        if 'Settings' not in self.config:
            self.config['Settings'] = {}
            
        self.config['Settings']['library_location'] = self.library_location
        
        try:
            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def on_close(self):
        """Handle window close event"""
        self.save_settings()
        self.root.destroy()
    
    def set_theme(self):
        style = ttk.Style()
        
        try:
            style.theme_use("clam")  # Use clam theme as a base
        except:
            pass
        
        bg_color = "#2E3440"
        fg_color = "#ECEFF4"
        accent_color = "#5E81AC"
        secondary_color = "#4C566A"
        
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground=fg_color)
        style.configure("TButton", background=accent_color, foreground=fg_color, borderwidth=0, font=("Arial", 10, "bold"))
        style.map("TButton", 
            background=[("active", secondary_color), ("disabled", "#3B4252")],
            foreground=[("disabled", "#D8DEE9")]
        )
        
        style.configure("TEntry", fieldbackground=secondary_color, foreground=fg_color, bordercolor=accent_color)
        style.map("TEntry", fieldbackground=[("readonly", secondary_color)])
        
        style.configure("TLabelframe", background=bg_color, foreground=fg_color)
        style.configure("TLabelframe.Label", background=bg_color, foreground=accent_color, font=("Arial", 11, "bold"))
        
        style.configure("Treeview", 
                        background=secondary_color, 
                        foreground=fg_color, 
                        rowheight=25, 
                        fieldbackground=secondary_color)
        style.map("Treeview", 
                  background=[("selected", accent_color)],
                  foreground=[("selected", fg_color)])
        
        style.configure("Treeview.Heading", 
                        background=bg_color, 
                        foreground=accent_color, 
                        relief="flat",
                        font=("Arial", 10, "bold"))
        style.map("Treeview.Heading", 
                  background=[("active", secondary_color)])
        
        self.root.configure(bg=bg_color)
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        app_title = ttk.Label(header_frame, text="Music Library Extender", font=("Arial", 18, "bold"))
        app_title.pack(side=tk.LEFT)
        
        search_frame = ttk.LabelFrame(main_frame, text="Search")
        search_frame.pack(fill=tk.X, expand=False, pady=(0, 15))
        
        search_entry_frame = ttk.Frame(search_frame)
        search_entry_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_entry_frame, textvariable=self.search_var, font=("Arial", 11))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.search_button = ttk.Button(search_entry_frame, text="Search", command=self.search)
        self.search_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        lib_frame = ttk.LabelFrame(main_frame, text="Library Location")
        lib_frame.pack(fill=tk.X, expand=False, pady=(0, 15))
        
        lib_entry_frame = ttk.Frame(lib_frame)
        lib_entry_frame.pack(fill=tk.X, expand=True, padx=10, pady=10)
        
        self.lib_var = tk.StringVar(value=self.library_location)
        self.lib_entry = ttk.Entry(lib_entry_frame, textvariable=self.lib_var, font=("Arial", 11))
        self.lib_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.lib_button = ttk.Button(lib_entry_frame, text="Browse", command=self.choose_library)
        self.lib_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        results_frame = ttk.LabelFrame(main_frame, text="Search Results")
        results_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        tree_frame = ttk.Frame(results_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.results_tree = ttk.Treeview(tree_frame, columns=("title", "channel", "duration"), show="headings")
        self.results_tree.heading("title", text="Title")
        self.results_tree.heading("channel", text="Channel")
        self.results_tree.heading("duration", text="Duration")
        self.results_tree.column("title", width=450)
        self.results_tree.column("channel", width=250)
        self.results_tree.column("duration", width=100)
        self.results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.results_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_tree.configure(yscrollcommand=scrollbar.set)
        
        self.results_tree.bind("<<TreeviewSelect>>", self.on_video_select)
        
        preview_container = ttk.Frame(main_frame)  # Container with fixed height
        preview_container.pack(fill=tk.X, pady=(0, 15))
        
        self.preview_frame = ttk.LabelFrame(preview_container, text="Preview")
        self.preview_frame.pack(fill=tk.BOTH, expand=True)
        
        self.thumbnail_frame = ttk.Frame(self.preview_frame)
        self.thumbnail_frame.pack(side=tk.LEFT, padx=15, pady=15)
        
        self.thumbnail_label = ttk.Label(self.thumbnail_frame, text="Select a video to see preview")
        self.thumbnail_label.pack(side=tk.TOP)
        
        # counter for multiple artworks
        self.artwork_counter_var = tk.StringVar(value="")
        self.artwork_counter = ttk.Label(self.thumbnail_frame, textvariable=self.artwork_counter_var, font=("Arial", 10))
        self.artwork_counter.pack(side=tk.TOP, pady=(5, 0))
        
        self.thumbnail_label.bind("<Button-1>", self.show_artwork_selector)
        
        details_frame = ttk.Frame(self.preview_frame)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10), pady=15)
        
        # Video title
        self.title_var = tk.StringVar()
        ttk.Label(details_frame, text="Title:", font=("Arial", 11)).grid(row=0, column=0, sticky=tk.W, pady=5)
        self.title_entry = ttk.Entry(details_frame, textvariable=self.title_var, width=40, font=("Arial", 11))
        self.title_entry.grid(row=0, column=1, sticky=tk.W+tk.E, pady=5)
        
        # Artist
        self.artist_var = tk.StringVar()
        ttk.Label(details_frame, text="Artist:", font=("Arial", 11)).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.artist_entry = ttk.Entry(details_frame, textvariable=self.artist_var, width=40, font=("Arial", 11))
        self.artist_entry.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5)
        
        # Album
        self.album_var = tk.StringVar()
        ttk.Label(details_frame, text="Album:", font=("Arial", 11)).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.album_entry = ttk.Entry(details_frame, textvariable=self.album_var, width=40, font=("Arial", 11))
        self.album_entry.grid(row=2, column=1, sticky=tk.W+tk.E, pady=5)
        
        # Year
        self.year_var = tk.StringVar()
        ttk.Label(details_frame, text="Year:", font=("Arial", 11)).grid(row=3, column=0, sticky=tk.W, pady=5)
        self.year_entry = ttk.Entry(details_frame, textvariable=self.year_var, width=40, font=("Arial", 11))
        self.year_entry.grid(row=3, column=1, sticky=tk.W+tk.E, pady=5)
        
        # Genre
        self.genre_var = tk.StringVar()
        ttk.Label(details_frame, text="Genre:", font=("Arial", 11)).grid(row=4, column=0, sticky=tk.W, pady=5)
        self.genre_entry = ttk.Entry(details_frame, textvariable=self.genre_var, width=40, font=("Arial", 11))
        self.genre_entry.grid(row=4, column=1, sticky=tk.W+tk.E, pady=5)
        
        # Track Number
        self.track_var = tk.StringVar()
        ttk.Label(details_frame, text="Track #:", font=("Arial", 11)).grid(row=5, column=0, sticky=tk.W, pady=5)
        self.track_entry = ttk.Entry(details_frame, textvariable=self.track_var, width=40, font=("Arial", 11))
        self.track_entry.grid(row=5, column=1, sticky=tk.W+tk.E, pady=5)
        
        details_frame.columnconfigure(1, weight=1)
        
        lyrics_section_frame = ttk.Frame(self.preview_frame)
        lyrics_section_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15), pady=15)
        
        lyrics_header = ttk.Frame(lyrics_section_frame)
        lyrics_header.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(lyrics_header, text="Lyrics:", font=("Arial", 11)).pack(side=tk.LEFT)
        
        self.fetch_lyrics_button = ttk.Button(lyrics_header, text="Fetch Lyrics", command=self.fetch_lyrics)
        self.fetch_lyrics_button.pack(side=tk.RIGHT, padx=(5, 0))
        
        self.clear_lyrics_button = ttk.Button(lyrics_header, text="Clear", command=lambda: self.lyrics_text.delete(1.0, tk.END))
        self.clear_lyrics_button.pack(side=tk.RIGHT)
        
        self.lyrics_frame = ttk.Frame(lyrics_section_frame)
        self.lyrics_frame.pack(fill=tk.BOTH, expand=True)
        
        self.lyrics_text = tk.Text(self.lyrics_frame, height=10, width=50, font=("Arial", 10), wrap=tk.WORD)
        self.lyrics_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        lyrics_scrollbar = ttk.Scrollbar(self.lyrics_frame, orient=tk.VERTICAL, command=self.lyrics_text.yview)
        lyrics_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lyrics_text.config(yscrollcommand=lyrics_scrollbar.set)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, expand=False)
        
        self.download_button = ttk.Button(button_frame, text="Download", command=self.download_video, state=tk.DISABLED)
        self.download_button.pack(side=tk.RIGHT)
        
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var.set("Ready")
    
    def choose_library(self):
        directory = filedialog.askdirectory(initialdir=self.library_location)
        if directory:
            self.library_location = directory
            self.lib_var.set(directory)
            self.save_settings()
    
    def search(self):
        query = self.search_var.get().strip()
        if not query:
            messagebox.showwarning("Search", "Please enter a search term")
            return
            
        self.status_var.set(f"Searching for: {query}...")
        
        # Clear previous results
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
            
        # Start search in a separate thread
        threading.Thread(target=self._search_thread, args=(query,), daemon=True).start()
    
    def _search_thread(self, query):
        try:
            videos = self._ytdlp_search(query)
            self.search_results = videos
            self.root.after(0, self._update_search_results)
            
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Error: {str(e)}"))
    
    def _ytdlp_search(self, query):
        """Search YouTube using yt-dlp"""
        results = []
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'default_search': 'ytsearch10', # Gets 10 results
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch10:{query}", download=False)
                if 'entries' in info:
                    for entry in info['entries']:
                        if not entry:
                            continue
                            
                        duration_secs = entry.get('duration', 0)
                        duration = time.strftime('%M:%S', time.gmtime(duration_secs)) if duration_secs else 'Unknown'
                        
                        video_url = entry.get('webpage_url')
                        if not video_url:
                            if entry.get('id'):
                                video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                            
                        video = {
                            "id": entry['id'],
                            "title": entry.get('title', 'Unknown Title'),
                            "channel": entry.get('uploader', 'Unknown Uploader'),
                            "duration": duration,
                            "thumbnail": entry.get('thumbnail'),
                            "webpage_url": video_url
                        }
                        results.append(video)
            except Exception as e:
                print(f"Search error: {str(e)}")
                
        return results
    
    def _update_search_results(self):
        for i, video in enumerate(self.search_results):
            self.results_tree.insert("", tk.END, iid=i, values=(
                video["title"],
                video["channel"],
                video["duration"]
            ))
        
        self.status_var.set(f"Found {len(self.search_results)} results")
    
    def on_video_select(self, event):
        selected_items = self.results_tree.selection()
        if selected_items:
            index = int(selected_items[0])
            self.selected_video = self.search_results[index]
            
            self._update_preview()
            self.download_button.config(state=tk.NORMAL)
    
    def _update_preview(self):
        if self.selected_video:
            title_parts = self.selected_video["title"].split(" - ")
            
            if len(title_parts) > 1:
                artist = title_parts[0].strip()
                title = " - ".join(title_parts[1:]).strip()
                title = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', title).strip()
            else:
                artist = self.selected_video["channel"]
                title = title_parts[0].strip()
                title = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', title).strip()
                parts = re.split(r'\s+by\s+', title, flags=re.IGNORECASE)
                if len(parts) > 1:
                    title = parts[0].strip()
                    artist = parts[1].strip()
            
            self.title_var.set(title)
            self.artist_var.set(artist)
            self.genre_var.set("")
            
            threading.Thread(target=self._fetch_metadata, args=(artist, title), daemon=True).start()
            
            if self.selected_video["thumbnail"]:
                threading.Thread(target=self._load_thumbnail, daemon=True).start()
            else:
                self.thumbnail_label.config(text="No thumbnail available")
    
    def show_artwork_selector(self, event):
        """Show the artwork selector dialog when thumbnail is clicked"""
        if hasattr(self, 'artwork_options') and len(self.artwork_options) > 1:
            print(f"Opening artwork selector with {len(self.artwork_options)} options")
            
            valid_options = []
            for i, option in enumerate(self.artwork_options):
                if 'data' in option and option['data'] and 'source' in option:
                    valid_options.append(option)
                else:
                    print(f"Skipping invalid artwork option {i}")
            
            if not valid_options:
                messagebox.showinfo("No Artwork", "No valid artwork options available")
                return
                
            dialog = ArtworkSelectorDialog(self.root, valid_options)
            self.root.wait_window(dialog)
            
            if dialog.selected_index is not None and 0 <= dialog.selected_index < len(valid_options):
                selected_artwork = valid_options[dialog.selected_index]
                self.album_art_data = selected_artwork['data']
                
                img_data = BytesIO(self.album_art_data)
                img = Image.open(img_data)
                img = img.resize((120, 120), Image.Resampling.LANCZOS)
                
                self.thumbnail_image = ImageTk.PhotoImage(img)
                self.thumbnail_label.config(image=self.thumbnail_image, text="")
                
                self.artwork_counter_var.set(f"Selected {dialog.selected_index + 1}/{len(valid_options)}")
                print(f"Selected artwork {dialog.selected_index + 1}/{len(valid_options)}")
    
    def _fetch_metadata(self, artist, title):
        """Fetch additional metadata from MusicBrainz or other sources"""
        try:
            self.root.after(0, lambda: self.status_var.set("Looking up metadata..."))
            self.artwork_options = []
            self.artwork_counter_var.set("")
            
            # Reset the track number to ensure we get fresh data
            self.track_var.set("")
            
            if hasattr(self, 'album_art_data'):
                delattr(self, 'album_art_data')
            
            threading.Thread(target=self._fetch_itunes_metadata, args=(artist, title), daemon=True).start()
            
            try:
                search_query = f"artist:{artist} AND recording:{title}"
                result = musicbrainzngs.search_recordings(query=search_query, limit=1)
                
                if result and 'recording-list' in result and result['recording-list']:
                    recording = result['recording-list'][0]
                    
                    if 'release-list' in recording and recording['release-list']:
                        release = recording['release-list'][0]
                        
                        # Set album title
                        album_title = release.get('title', '')
                        if album_title:
                            self.root.after(0, lambda: self.album_var.set(album_title))
                        
                        # Set release date/year
                        if 'date' in release:
                            release_date = release['date']
                            year_match = re.match(r'(\d{4})', release_date)
                            if year_match:
                                self.root.after(0, lambda: self.year_var.set(year_match.group(1)))
                        
                        # Try to get track number from the medium-list if available
                        if 'medium-list' in release:
                            for medium in release['medium-list']:
                                if 'track-list' in medium:
                                    for track in medium['track-list']:
                                        if 'recording' in track and track['recording']['id'] == recording['id']:
                                            # Found the track in this medium
                                            track_number = track.get('number')
                                            if track_number:
                                                self.root.after(0, lambda tn=track_number: self.track_var.set(tn))
                                                print(f"Found track number from MusicBrainz: {track_number}")
                                                break
                        
                        # If we have a release ID, try to get more detailed track info and cover art
                        release_id = release.get('id')
                        if release_id:
                            # Start thread to fetch album art
                            threading.Thread(target=self._fetch_album_art, args=(release_id,), daemon=True).start()
                            
                            # Also fetch more detailed release info including track position
                            threading.Thread(target=self._fetch_release_details, args=(release_id, recording['id']), daemon=True).start()
                    
                    # Get genre from tags
                    if 'tag-list' in recording:
                        genres = []
                        for tag in recording['tag-list']:
                            if tag.get('name') and tag.get('count', 0) > 0:
                                # Only use tags that might be genres
                                tag_name = tag['name'].lower()
                                if tag_name in ['rock', 'pop', 'jazz', 'classical', 'electronic', 'hip-hop', 'rap', 
                                              'metal', 'country', 'folk', 'blues', 'r&b', 'reggae', 'indie', 
                                              'dance', 'ambient', 'punk', 'latin']:
                                    genres.append(tag['name'])
                        
                        if genres:
                            self.root.after(0, lambda: self.genre_var.set(", ".join(genres[:2])))
            except Exception as e:
                print(f"Error fetching metadata from MusicBrainz: {str(e)}")
        except Exception as e:
            print(f"Error in metadata fetching: {str(e)}")
            self.root.after(0, lambda: self.status_var.set("Error fetching metadata"))
    
    def _fetch_itunes_metadata(self, artist, title):
        """Fetch metadata from iTunes API as a fallback"""
        try:
            search_query = f"{artist} {title}"
            itunes_url = f"https://itunes.apple.com/search?term={search_query.replace(' ', '+')}&media=music&limit=1"
            
            response = requests.get(itunes_url)
            if response.status_code == 200:
                data = response.json()
                if data.get('resultCount', 0) > 0:
                    result = data['results'][0]
                    
                    # Set album
                    if result.get('collectionName'):
                        self.root.after(0, lambda: self.album_var.set(result['collectionName']))
                    
                    # Set year
                    if result.get('releaseDate'):
                        year_match = re.match(r'(\d{4})', result['releaseDate'])
                        if year_match:
                            self.root.after(0, lambda: self.year_var.set(year_match.group(1)))
                    
                    # Set genre
                    if result.get('primaryGenreName'):
                        self.root.after(0, lambda: self.genre_var.set(result['primaryGenreName']))
                    
                    # Get artwork
                    if result.get('artworkUrl100'):
                        artwork_url = result['artworkUrl100'].replace('100x100', '600x600')
                        threading.Thread(target=self._fetch_itunes_art, args=(artwork_url,), daemon=True).start()
                    
                    self.root.after(0, lambda: self.status_var.set("Metadata found from iTunes"))
                else:
                    self.root.after(0, lambda: self.status_var.set("No iTunes metadata found"))
            else:
                self.root.after(0, lambda: self.status_var.set("Error fetching iTunes metadata"))
        except Exception as e:
            print(f"Error fetching iTunes metadata: {str(e)}")
    
    def _fetch_itunes_art(self, artwork_url):
        """Fetch album art from iTunes"""
        try:
            response = requests.get(artwork_url)
            if response.status_code == 200:
                self.album_art_data = response.content
                
                self.artwork_options.append({
                    'source': 'iTunes',
                    'data': response.content
                })
                
                img_data = BytesIO(response.content)
                img = Image.open(img_data)
                img = img.resize((120, 120), Image.Resampling.LANCZOS)
                
                self.thumbnail_image = ImageTk.PhotoImage(img)
                self.root.after(0, lambda: self.thumbnail_label.config(
                    image=self.thumbnail_image, text=""
                ))
                
                self.root.after(0, lambda: self._update_artwork_counter())
                
                print(f"Successfully fetched iTunes artwork, size: {len(response.content) // 1024}KB")
        except Exception as e:
            print(f"Error fetching iTunes album art: {str(e)}")
    
    def _fetch_album_art(self, release_id):
        """Try to get album art from MusicBrainz/Cover Art Archive"""
        try:
            url = f"https://coverartarchive.org/release/{release_id}/front"
            response = requests.get(url, stream=True)
            
            if response.status_code == 200:
                art_data = response.content
                
                self.artwork_options.append({
                    'source': 'MusicBrainz',
                    'data': art_data
                })
                
                if not hasattr(self, 'album_art_data'):
                    self.album_art_data = art_data
                    
                    img_data = BytesIO(art_data)
                    img = Image.open(img_data)
                    img = img.resize((120, 120), Image.Resampling.LANCZOS)
                    
                    self.thumbnail_image = ImageTk.PhotoImage(img)
                    self.root.after(0, lambda: self.thumbnail_label.config(
                        image=self.thumbnail_image, text=""
                    ))
                
                self.root.after(0, lambda: self._update_artwork_counter())
                
                print(f"Successfully fetched MusicBrainz artwork, size: {len(art_data) // 1024}KB")
                
                try:
                    images_url = f"https://coverartarchive.org/release/{release_id}"
                    images_response = requests.get(images_url)
                    if images_response.status_code == 200:
                        images_data = images_response.json()
                        if 'images' in images_data:
                            for image in images_data['images']:
                                if image.get('front') == True:
                                    continue  # Skip front cover, we already have it
                                    
                                if 'image' in image:
                                    img_url = image['image']
                                    threading.Thread(target=self._fetch_additional_art, 
                                                    args=(img_url, f'MusicBrainz ({image.get("types", ["Additional"])[0]})'),
                                                    daemon=True).start()
                except Exception as e:
                    print(f"Error fetching additional MusicBrainz artwork: {str(e)}")
        except Exception as e:
            print(f"Error fetching MusicBrainz album art: {str(e)}")
    
    def _fetch_additional_art(self, url, source):
        """Fetch additional artwork from a URL"""
        try:
            response = requests.get(url, stream=True)
            
            if response.status_code == 200:
                self.artwork_options.append({
                    'source': source,
                    'data': response.content
                })
                
                self.root.after(0, lambda: self._update_artwork_counter())
                
                print(f"Successfully fetched additional artwork from {source}, size: {len(response.content) // 1024}KB")
        except Exception as e:
            print(f"Error fetching additional artwork: {str(e)}")
    
    def _load_thumbnail(self):
        try:
            thumbnail_url = self.selected_video["thumbnail"]
            
            if not thumbnail_url:
                self.root.after(0, lambda: self.thumbnail_label.config(
                    text="No thumbnail available"
                ))
                return
            
            response = requests.get(thumbnail_url)
            if response.status_code != 200:
                self.root.after(0, lambda: self.thumbnail_label.config(
                    text="Failed to load thumbnail"
                ))
                return
                
            img_data = BytesIO(response.content)
            
            try:
                img = Image.open(img_data)
                img = img.resize((120, 90), Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"Invalid image data: {str(e)}")
                self.root.after(0, lambda: self.thumbnail_label.config(
                    text="Invalid thumbnail image"
                ))
                return
            
            self.thumbnail_image = ImageTk.PhotoImage(img)
            
            self.artwork_options.append({
                'source': 'Video Thumbnail',
                'data': response.content
            })
            
            self.root.after(0, lambda: self.thumbnail_label.config(
                image=self.thumbnail_image, text=""
            ))
            
            self.root.after(0, lambda: self._update_artwork_counter())
            
            print(f"Successfully loaded video thumbnail, size: {len(response.content) // 1024}KB")
            
        except Exception as e:
            print(f"Error loading thumbnail: {str(e)}")
            self.root.after(0, lambda: self.thumbnail_label.config(
                text="Could not load thumbnail"
            ))
    
    def _update_artwork_counter(self):
        """Update the artwork counter label"""
        if len(self.artwork_options) > 1:
            current_index = 0
            if hasattr(self, 'album_art_data'):
                for i, option in enumerate(self.artwork_options):
                    if option['data'] == self.album_art_data:
                        current_index = i
                        break
            
            self.artwork_counter_var.set(f"Click to choose ({current_index + 1}/{len(self.artwork_options)})")
            self.thumbnail_label.config(cursor="hand2")  # Hand cursor to indicate clickable
            print(f"Updated artwork counter: {current_index + 1}/{len(self.artwork_options)}")
        else:
            self.artwork_counter_var.set("")
            self.thumbnail_label.config(cursor="")
    
    def download_video(self):
        if not self.selected_video:
            return
            
        save_dir = self.library_location
        
        title = self.title_var.get()
        artist = self.artist_var.get()
        
        valid_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-").replace(":", "-")
        save_path = os.path.join(save_dir, f"{valid_filename}.mp3")
        
        threading.Thread(target=self._download_thread, args=(save_path,), daemon=True).start()
        
        self.status_var.set("Download started...")
        self.download_button.config(state=tk.DISABLED)
    
    def _download_thread(self, save_path):
        try:
            video_url = self.selected_video.get("webpage_url")
            if not video_url:
                if self.selected_video.get("id"):
                    video_url = f"https://www.youtube.com/watch?v={self.selected_video['id']}"
                else:
                    raise Exception("No valid video URL found")
            
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_filename = os.path.join(temp_dir, "audio")
                
                # Configure yt-dlp options
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': temp_filename,
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'quiet': True,
                    'no_warnings': True
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self.root.after(0, lambda: self.status_var.set("Downloading audio..."))
                    ydl.download([video_url])
                
                downloaded_file = temp_filename + ".mp3"
                if os.path.exists(downloaded_file):
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    
                    shutil.copy2(downloaded_file, save_path)
                    
                    self.root.after(0, lambda: self.status_var.set("Setting metadata..."))
                    if self._set_metadata(save_path):
                        self.root.after(0, lambda: self.status_var.set(f"Download complete: {os.path.basename(save_path)}"))
                    else:
                        self.root.after(0, lambda: self.status_var.set(f"Download complete but metadata failed: {os.path.basename(save_path)}"))
                    
                    self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
                    self.root.after(0, lambda: messagebox.showinfo("Download Complete", f"File saved to: {save_path}"))
                else:
                    raise Exception("Downloaded file not found")
                
        except Exception as e:
            self.root.after(0, lambda: self._show_error(f"Download error: {str(e)}"))
            self.root.after(0, lambda: self.download_button.config(state=tk.NORMAL))
    
    def _set_metadata(self, file_path):
        """Set ID3 metadata for the downloaded MP3 file"""
        try:
            print(f"Setting metadata for {file_path}")
            
            try:
                audio = MP3(file_path)
                audio.delete()
                audio.save()
                print("Deleted existing tags")
            except Exception as e:
                print(f"Error clearing tags: {str(e)}")
            
            tags = ID3()
            
            # Set title
            if self.title_var.get():
                tags.add(TIT2(encoding=3, text=self.title_var.get()))
                print(f"Added title: {self.title_var.get()}")
            
            # Set artist
            if self.artist_var.get():
                tags.add(TPE1(encoding=3, text=self.artist_var.get()))
                print(f"Added artist: {self.artist_var.get()}")
            
            # Set album if provided
            if self.album_var.get():
                tags.add(TALB(encoding=3, text=self.album_var.get()))
                print(f"Added album: {self.album_var.get()}")
            
            # Set year if provided
            if self.year_var.get():
                tags.add(TDRC(encoding=3, text=self.year_var.get()))
                print(f"Added year: {self.year_var.get()}")
            
            # Set genre if provided
            if self.genre_var.get():
                tags.add(TCON(encoding=3, text=self.genre_var.get()))
                print(f"Added genre: {self.genre_var.get()}")
                
            # Set track number if provided
            if self.track_var.get():
                tags.add(TRCK(encoding=3, text=self.track_var.get()))
                print(f"Added track number: {self.track_var.get()}")
            
            # Add lyrics if provided
            lyrics_text = self.lyrics_text.get(1.0, tk.END).strip()
            if lyrics_text and lyrics_text != "No lyrics found. You can add them manually.":
                tags.add(USLT(
                    encoding=3,  # UTF-8
                    lang='eng',  # Language code (English)
                    desc='',     # Description
                    text=lyrics_text
                ))
                print("Added lyrics to tags")
            
            # Add album art if we have it
            has_art = self._add_album_art_to_tags(tags)
            if has_art:
                print("Added album art to tags")
            
            # Save the tags to the file
            tags.save(file_path)
            print("Tags saved to file")
            
            # Verify that the tags were added correctly
            try:
                verification = ID3(file_path)
                if verification:
                    print("Tag verification successful")
                    return True
                else:
                    print("Tag verification failed - no tags found")
                    return False
            except Exception as e:
                print(f"Tag verification error: {str(e)}")
                return False
                
        except Exception as e:
            print(f"Error setting metadata: {str(e)}")
            self.root.after(0, lambda: self._show_error(f"Metadata error: {str(e)}"))
            return False
    
    def _add_album_art_to_tags(self, tags):
        """Add album art to ID3 tags"""
        try:
            # First try to use album art we found from MusicBrainz or iTunes if available
            if hasattr(self, 'album_art_data'):
                print("Using previously fetched album art")
                tags.add(APIC(
                    encoding=3,  # UTF-8
                    mime='image/jpeg',
                    type=3,  # Cover image
                    desc='Cover',
                    data=self.album_art_data
                ))
                return True
            
            # If not, try to use the thumbnail from the video
            if self.selected_video and self.selected_video["thumbnail"]:
                print("Using video thumbnail as album art")
                response = requests.get(self.selected_video["thumbnail"])
                if response.status_code == 200:
                    # Add the image to the ID3 tag
                    tags.add(APIC(
                        encoding=3,  # UTF-8
                        mime='image/jpeg',
                        type=3,  # Cover image
                        desc='Cover',
                        data=response.content
                    ))
                    return True
            
            # If that failed, try to search for album art via iTunes API directly
            try:
                search_query = f"{self.artist_var.get()} {self.title_var.get()}"
                print(f"Searching iTunes for album art with query: {search_query}")
                itunes_url = f"https://itunes.apple.com/search?term={search_query.replace(' ', '+')}&media=music&limit=1"
                
                response = requests.get(itunes_url)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('resultCount', 0) > 0:
                        # Get the artwork URL and convert to a higher resolution version
                        artwork_url = data['results'][0].get('artworkUrl100', '')
                        if artwork_url:
                            # Get larger image (replace '100x100' with '600x600')
                            artwork_url = artwork_url.replace('100x100', '600x600')
                            print(f"Found iTunes artwork: {artwork_url}")
                            img_response = requests.get(artwork_url)
                            if img_response.status_code == 200:
                                tags.add(APIC(
                                    encoding=3,
                                    mime='image/jpeg',
                                    type=3,
                                    desc='Cover',
                                    data=img_response.content
                                ))
                                return True
            except Exception as e:
                print(f"Error in iTunes album art fallback: {str(e)}")
            
            print("No album art could be found")
            return False
            
        except Exception as e:
            print(f"Error adding album art to tags: {str(e)}")
            return False
    
    def _show_error(self, message):
        messagebox.showerror("Error", message)
        self.status_var.set("Error occurred")
        
    def fetch_lyrics(self):
        """Fetch lyrics for the currently selected song"""
        if not self.selected_video:
            messagebox.showinfo("Fetch Lyrics", "Please select a song first")
            return
            
        self.lyrics_text.delete(1.0, tk.END)
        
        artist = self.artist_var.get().strip()
        title = self.title_var.get().strip()
        
        if not artist or not title:
            messagebox.showinfo("Fetch Lyrics", "Artist and title are required to fetch lyrics")
            return
            
        self.status_var.set(f"Fetching lyrics for {artist} - {title}...")
        
        threading.Thread(target=self._fetch_lyrics_thread, args=(artist, title), daemon=True).start()
    
    def _fetch_lyrics_thread(self, artist, title):
        """Thread to fetch lyrics from various sources"""
        lyrics = None
        source = None
        
        try:
            # Try Genius API first
            lyrics, source = self._fetch_lyrics_from_genius(artist, title)
                
            if not lyrics:
                # Try Musixmatch as second option
                lyrics, source = self._fetch_lyrics_from_musixmatch(artist, title)
                
            if not lyrics:
                # Try lyrics.ovh as a third option
                lyrics, source = self._fetch_lyrics_from_lyricsovh(artist, title)
                
            # Update the UI with the lyrics
            self.root.after(0, lambda: self._update_lyrics_ui(lyrics, source))
            
        except Exception as e:
            print(f"Error fetching lyrics: {str(e)}")
            self.root.after(0, lambda: self.status_var.set(f"Error fetching lyrics: {str(e)}"))
            
    def _fetch_lyrics_from_genius(self, artist, title):
        """Fetch lyrics from Genius via their API (search only) and web scraping"""
        try:
            search_query = f"{artist} {title}".replace(' ', '%20')
            search_url = f"https://genius.com/api/search/multi?q={search_query}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                
                if 'response' in data and 'sections' in data['response']:
                    for section in data['response']['sections']:
                        if section['type'] == 'song':
                            if 'hits' in section and len(section['hits']) > 0:
                                song = section['hits'][0]['result']
                                song_url = song['url']
                                
                                song_response = requests.get(song_url, headers=headers)
                                if song_response.status_code == 200:
                                    import re
                                    html_content = song_response.text
                                    
                                    lyrics_pattern = r'<div data-lyrics-container="true"[^>]*>(.*?)</div>'
                                    lyrics_matches = re.findall(lyrics_pattern, html_content, re.DOTALL)
                                    
                                    if lyrics_matches:
                                        combined_lyrics = "\n".join(lyrics_matches)
                                        
                                        combined_lyrics = combined_lyrics.replace('<br>', '\n')
                                        combined_lyrics = combined_lyrics.replace('<br/>', '\n')
                                        combined_lyrics = combined_lyrics.replace('<BR>', '\n')
                                        
                                        lyrics = re.sub(r'<[^>]+>', '', combined_lyrics)
                                        
                                        lyrics = html.unescape(lyrics)
                                        
                                        lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)
                                        lyrics = lyrics.strip()
                                        
                                        return lyrics, "Genius"
            
            return None, None
            
        except Exception as e:
            print(f"Error fetching lyrics from Genius: {str(e)}")
            return None, None
    
    def _fetch_lyrics_from_musixmatch(self, artist, title):
        """Fetch lyrics from Musixmatch"""
        try:
            search_query = f"{artist} {title}".replace(' ', '%20')
            search_url = f"https://api.musixmatch.com/ws/1.1/matcher.lyrics.get?format=json&q_track={title}&q_artist={artist}&apikey=2d782bc7a52a41ba2fc1ef05b9cf40d7"
            
            response = requests.get(search_url)
            if response.status_code == 200:
                data = response.json()
                
                if data['message']['header']['status_code'] == 200:
                    if 'lyrics' in data['message']['body']:
                        lyrics = data['message']['body']['lyrics']['lyrics_body']
                        
                        if "..." in lyrics and "Paroles" in lyrics:
                            lyrics = lyrics.split("...")[0].strip() + "..."
                            
                        return lyrics, "MusixMatch"
            
            return None, None
            
        except Exception as e:
            print(f"Error fetching lyrics from Musixmatch: {str(e)}")
            return None, None
    
    def _fetch_lyrics_from_lyricsovh(self, artist, title):
        """Fetch lyrics from lyrics.ovh API"""
        try:
            api_url = f"https://api.lyrics.ovh/v1/{artist.replace(' ', '%20')}/{title.replace(' ', '%20')}"
            
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                if 'lyrics' in data:
                    return data['lyrics'], "Lyrics.ovh"
            
            return None, None
            
        except Exception as e:
            print(f"Error fetching lyrics from Lyrics.ovh: {str(e)}")
            return None, None
    
    def _update_lyrics_ui(self, lyrics, source):
        """Update the UI with fetched lyrics"""
        if lyrics:
            try:
                lyrics = html.unescape(lyrics)
                
                lyrics = lyrics.replace('<br>', '\n')
                lyrics = lyrics.replace('<br/>', '\n')
                
                # Fix cases where lyrics are all in one line
                # Look for common section markers and add line breaks
                markers = [
                    r'\[Verse\s?\d*\]', r'\[Chorus\]', r'\[Pre-Chorus\]', r'\[Hook\]', r'\[Intro\]', 
                    r'\[Outro\]', r'\[Bridge\]', r'\[Refrain\]', r'\[Part\s?\d*\]', r'\[Songtext.*?\]',
                    r'\[Strophe\s?\d*\]', r'\[Refrain\]', r'\[Solo\]'
                ]
                
                for marker in markers:
                    lyrics = re.sub(f"({marker})", r"\n\1\n", lyrics, flags=re.IGNORECASE)
                
                if len(lyrics.split('\n')) < 3:
                    lyrics = re.sub(r'([,.!?])\s+([A-ZÄÖÜa-zäöüß])', r'\1\n\2', lyrics)
                
                # Fix common patterns in lyrics that should create line breaks
                # Pattern: "word (Section marker)" should break after the word
                lyrics = re.sub(r'(\w+)\s+(\[\w+)', r'\1\n\2', lyrics)
                
                if len(lyrics.split('\n')) < 5 and len(lyrics) > 200:
                    lyrics = re.sub(r'([.!?])\s+', r'\1\n', lyrics)
                    
                    lyrics = re.sub(r',\s+([A-ZÄÖÜ])', r',\n\1', lyrics)
                    
                    lyrics = re.sub(r'(\])\s*(?!\n)', r'\1\n', lyrics)
                
                while '\n\n\n' in lyrics:
                    lyrics = lyrics.replace('\n\n\n', '\n\n')
                
                lyrics = lyrics.strip()
            except Exception as e:
                print(f"Error cleaning lyrics: {str(e)}")
            
            self.lyrics_text.delete(1.0, tk.END)
            self.lyrics_text.insert(tk.END, lyrics)
            
            self.status_var.set(f"Lyrics found from {source}")
        else:
            # No lyrics found
            self.lyrics_text.delete(1.0, tk.END)
            self.lyrics_text.insert(tk.END, "No lyrics found. You can add them manually.")
            
            self.status_var.set("No lyrics found")
    
    def _fetch_release_details(self, release_id, recording_id):
        """Fetch more detailed release info from MusicBrainz including track position"""
        try:
            # Get full release info with MusicBrainz API
            release = musicbrainzngs.get_release_by_id(release_id, includes=["recordings", "media"])
            
            if not release or 'release' not in release:
                print(f"No detailed release info found for {release_id}")
                return
                
            release_data = release['release']
            
            # Look for our recording in the media/tracks
            if 'medium-list' in release_data:
                for medium in release_data['medium-list']:
                    if 'track-list' in medium:
                        disc_num = medium.get('position', '1')
                        
                        for track in medium['track-list']:
                            if 'recording' in track and track['recording']['id'] == recording_id:
                                # Found our track
                                track_num = track.get('position', '')
                                if track_num:
                                    # Format as "disc/track" if multi-disc release, otherwise just track number
                                    track_number = f"{disc_num}/{track_num}" if int(disc_num) > 1 else track_num
                                    self.root.after(0, lambda tn=track_number: self.track_var.set(tn))
                                    print(f"Found detailed track position from MusicBrainz: {track_number}")
                                    return
        except Exception as e:
            print(f"Error fetching detailed release info from MusicBrainz: {str(e)}")
        
class CLIHandler:
    """Command line interface handler for MusicLibraryExtender"""
    
    def __init__(self):
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        self.config = configparser.ConfigParser()
        self.library_location = os.path.join(os.path.expanduser("~"), "Music")
        self.load_settings()
        
        # Initialize MusicBrainz API for metadata
        musicbrainzngs.set_useragent("MusicLibraryExtender", "1.0.0", "https://github.com/TheBeaconCrafter/MusicLibraryExtender")
        
        self.console = Console()
        self.last_search_results = []
        
        # Load cached search results if they exist
        self.search_cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".search_cache.json")
        self._load_search_cache()
    
    def _load_search_cache(self):
        """Load cached search results from file"""
        try:
            if os.path.exists(self.search_cache_file):
                with open(self.search_cache_file, 'r') as f:
                    self.last_search_results = json.load(f)
                    self.console.print(f"[dim]Loaded {len(self.last_search_results)} cached search results[/dim]")
        except Exception as e:
            self.console.print(f"[yellow]Could not load search cache: {e}[/yellow]")
            self.last_search_results = []
            
    def _save_search_cache(self):
        """Save search results to cache file"""
        try:
            with open(self.search_cache_file, 'w') as f:
                json.dump(self.last_search_results, f)
        except Exception as e:
            self.console.print(f"[yellow]Could not save search cache: {e}[/yellow]")
    
    def load_settings(self):
        """Load settings from the config file or use defaults"""
        if os.path.exists(self.config_file):
            try:
                self.config.read(self.config_file)
                if 'Settings' in self.config:
                    if 'library_location' in self.config['Settings']:
                        saved_path = self.config['Settings']['library_location']
                        if os.path.exists(saved_path):
                            self.library_location = saved_path
            except Exception as e:
                self.console.print(f"[red]Error loading settings: {e}[/red]")
    
    def save_settings(self):
        """Save settings to the config file"""
        if 'Settings' not in self.config:
            self.config['Settings'] = {}
            
        self.config['Settings']['library_location'] = self.library_location
        
        try:
            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
        except Exception as e:
            self.console.print(f"[red]Error saving settings: {e}[/red]")
    
    def search_videos(self, query, limit=10, json_output=False):
        """Search for videos and display results"""
        self.console.print(f"[bold blue]Searching for:[/bold blue] {query}")
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',
                'default_search': f'ytsearch{limit}',
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                if 'entries' in info:
                    results = []
                    
                    for i, entry in enumerate(info['entries']):
                        if not entry:
                            continue
                            
                        duration_secs = entry.get('duration', 0)
                        duration = time.strftime('%M:%S', time.gmtime(duration_secs)) if duration_secs else 'Unknown'
                        
                        video_url = entry.get('webpage_url')
                        if not video_url and entry.get('id'):
                            video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                            
                        result = {
                            "id": entry['id'],
                            "title": entry.get('title', 'Unknown Title'),
                            "channel": entry.get('uploader', 'Unknown Uploader'),
                            "duration": duration,
                            "thumbnail": entry.get('thumbnail'),
                            "webpage_url": video_url
                        }
                        results.append(result)
                    
                    # Store results for later use
                    self.last_search_results = results
                    # Save to cache file for persistence between commands
                    self._save_search_cache()
                    
                    if json_output:
                        print(json.dumps(results, indent=2))
                    else:
                        table = Table(title="Search Results")
                        table.add_column("#", justify="right", style="cyan", no_wrap=True)
                        table.add_column("Title", style="white")
                        table.add_column("Channel", style="green")
                        table.add_column("Duration", justify="right", style="blue")
                        table.add_column("URL", style="magenta")
                        
                        for i, video in enumerate(results):
                            table.add_row(
                                str(i+1),
                                video["title"],
                                video["channel"],
                                video["duration"],
                                video["webpage_url"]
                            )
                        
                        self.console.print(table)
                    
                    return results
                else:
                    self.console.print("[red]No results found[/red]")
                    return []
        except Exception as e:
            self.console.print(f"[red]Search error: {str(e)}[/red]")
            return []
    
    def get_metadata(self, artist, title):
        """Fetch metadata for the specified artist and title"""
        self.console.print(f"[bold blue]Looking up metadata for:[/bold blue] {artist} - {title}")
        
        metadata = {
            "artist": artist,
            "title": title,
            "album": "",
            "year": "",
            "genre": "",
            "track_number": "",
            "artwork_url": None,
            "lyrics": None
        }
        
        # Try to get metadata from MusicBrainz
        try:
            search_query = f"artist:{artist} AND recording:{title}"
            result = musicbrainzngs.search_recordings(query=search_query, limit=1)
            
            if result and 'recording-list' in result and result['recording-list']:
                recording = result['recording-list'][0]
                
                if 'release-list' in recording and recording['release-list']:
                    release = recording['release-list'][0]
                    
                    # Set album title
                    album_title = release.get('title', '')
                    if album_title:
                        metadata["album"] = album_title
                    
                    # Set release date/year
                    if 'date' in release:
                        release_date = release['date']
                        year_match = re.match(r'(\d{4})', release_date)
                        if year_match:
                            metadata["year"] = year_match.group(1)
                    
                    # Try to get track number
                    if 'medium-list' in release:
                        for medium in release['medium-list']:
                            if 'track-list' in medium:
                                for track in medium['track-list']:
                                    if 'recording' in track and track['recording']['id'] == recording['id']:
                                        track_number = track.get('number')
                                        if track_number:
                                            metadata["track_number"] = track_number
                                            break
                    
                    # Get cover art URL if available
                    release_id = release.get('id')
                    if release_id:
                        try:
                            # Check if artwork exists
                            url = f"https://coverartarchive.org/release/{release_id}/front-500"
                            response = requests.head(url)
                            if response.status_code == 307:  # Redirect to the actual image
                                metadata["artwork_url"] = url
                        except Exception as e:
                            self.console.print(f"[yellow]Error checking artwork: {str(e)}[/yellow]")
                
                # Get genre from tags
                if 'tag-list' in recording:
                    genres = []
                    for tag in recording['tag-list']:
                        if tag.get('name') and tag.get('count', 0) > 0:
                            tag_name = tag['name'].lower()
                            if tag_name in ['rock', 'pop', 'jazz', 'classical', 'electronic', 'hip-hop', 'rap', 
                                          'metal', 'country', 'folk', 'blues', 'r&b', 'reggae', 'indie', 
                                          'dance', 'ambient', 'punk', 'latin']:
                                genres.append(tag['name'])
                    
                    if genres:
                        metadata["genre"] = ", ".join(genres[:2])
        
        except Exception as e:
            self.console.print(f"[yellow]MusicBrainz error: {str(e)}[/yellow]")
        
        # If we didn't get metadata from MusicBrainz, try iTunes
        if not metadata["album"] or not metadata["year"] or not metadata["genre"]:
            try:
                search_query = f"{artist} {title}"
                itunes_url = f"https://itunes.apple.com/search?term={search_query.replace(' ', '+')}&media=music&limit=1"
                
                response = requests.get(itunes_url)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('resultCount', 0) > 0:
                        result = data['results'][0]
                        
                        # Set album if not already set
                        if not metadata["album"] and result.get('collectionName'):
                            metadata["album"] = result['collectionName']
                        
                        # Set year if not already set
                        if not metadata["year"] and result.get('releaseDate'):
                            year_match = re.match(r'(\d{4})', result['releaseDate'])
                            if year_match:
                                metadata["year"] = year_match.group(1)
                        
                        # Set genre if not already set
                        if not metadata["genre"] and result.get('primaryGenreName'):
                            metadata["genre"] = result['primaryGenreName']
                        
                        # Set artwork URL if not already set
                        if not metadata["artwork_url"] and result.get('artworkUrl100'):
                            metadata["artwork_url"] = result['artworkUrl100'].replace('100x100', '600x600')
            
            except Exception as e:
                self.console.print(f"[yellow]iTunes API error: {str(e)}[/yellow]")
        
        # Get lyrics
        try:
            lyrics = self._fetch_lyrics(artist, title)
            if lyrics:
                metadata["lyrics"] = lyrics
        except Exception as e:
            self.console.print(f"[yellow]Lyrics fetching error: {str(e)}[/yellow]")
        
        # Print collected metadata
        self.console.print("\n[bold green]Metadata Results:[/bold green]")
        for key, value in metadata.items():
            if key == "lyrics":
                if value:
                    self.console.print(f"[bold]Lyrics:[/bold] [dim](Found - {len(value)} characters)[/dim]")
                else:
                    self.console.print(f"[bold]Lyrics:[/bold] [dim](Not found)[/dim]")
            elif key == "artwork_url":
                if value:
                    self.console.print(f"[bold]Cover Art:[/bold] [blue]{value}[/blue]")
                else:
                    self.console.print(f"[bold]Cover Art:[/bold] [dim](Not found)[/dim]")
            else:
                self.console.print(f"[bold]{key.replace('_', ' ').title()}:[/bold] {value}")
        
        return metadata
    
    def _fetch_lyrics(self, artist, title):
        """Try to fetch lyrics from multiple sources"""
        lyrics_sources = [
            self._fetch_lyrics_from_genius,
            self._fetch_lyrics_from_musixmatch,
            self._fetch_lyrics_from_lyricsovh
        ]
        
        for source_func in lyrics_sources:
            lyrics, source = source_func(artist, title)
            if lyrics:
                self.console.print(f"[green]Lyrics found from {source}[/green]")
                return lyrics
        
        return None
    
    def _fetch_lyrics_from_genius(self, artist, title):
        """Fetch lyrics from Genius via their API (search only) and web scraping"""
        try:
            search_query = f"{artist} {title}".replace(' ', '%20')
            search_url = f"https://genius.com/api/search/multi?q={search_query}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(search_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                
                if 'response' in data and 'sections' in data['response']:
                    for section in data['response']['sections']:
                        if section['type'] == 'song':
                            if 'hits' in section and len(section['hits']) > 0:
                                song = section['hits'][0]['result']
                                song_url = song['url']
                                
                                song_response = requests.get(song_url, headers=headers)
                                if song_response.status_code == 200:
                                    html_content = song_response.text
                                    
                                    lyrics_pattern = r'<div data-lyrics-container="true"[^>]*>(.*?)</div>'
                                    lyrics_matches = re.findall(lyrics_pattern, html_content, re.DOTALL)
                                    
                                    if lyrics_matches:
                                        combined_lyrics = "\n".join(lyrics_matches)
                                        
                                        combined_lyrics = combined_lyrics.replace('<br>', '\n')
                                        combined_lyrics = combined_lyrics.replace('<br/>', '\n')
                                        combined_lyrics = combined_lyrics.replace('<BR>', '\n')
                                        
                                        lyrics = re.sub(r'<[^>]+>', '', combined_lyrics)
                                        
                                        lyrics = html.unescape(lyrics)
                                        
                                        lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)
                                        lyrics = lyrics.strip()
                                        
                                        return lyrics, "Genius"
            
            return None, None
            
        except Exception as e:
            self.console.print(f"[yellow]Error fetching lyrics from Genius: {str(e)}[/yellow]")
            return None, None
    
    def _fetch_lyrics_from_musixmatch(self, artist, title):
        """Fetch lyrics from Musixmatch"""
        try:
            search_query = f"{artist} {title}".replace(' ', '%20')
            search_url = f"https://api.musixmatch.com/ws/1.1/matcher.lyrics.get?format=json&q_track={title}&q_artist={artist}&apikey=2d782bc7a52a41ba2fc1ef05b9cf40d7"
            
            response = requests.get(search_url)
            if response.status_code == 200:
                data = response.json()
                
                if data['message']['header']['status_code'] == 200:
                    if 'lyrics' in data['message']['body']:
                        lyrics = data['message']['body']['lyrics']['lyrics_body']
                        
                        if "..." in lyrics and "Paroles" in lyrics:
                            lyrics = lyrics.split("...")[0].strip() + "..."
                            
                        return lyrics, "MusixMatch"
            
            return None, None
            
        except Exception as e:
            self.console.print(f"[yellow]Error fetching lyrics from Musixmatch: {str(e)}[/yellow]")
            return None, None
    
    def _fetch_lyrics_from_lyricsovh(self, artist, title):
        """Fetch lyrics from lyrics.ovh API"""
        try:
            api_url = f"https://api.lyrics.ovh/v1/{artist.replace(' ', '%20')}/{title.replace(' ', '%20')}"
            
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                if 'lyrics' in data:
                    return data['lyrics'], "Lyrics.ovh"
            
            return None, None
            
        except Exception as e:
            self.console.print(f"[yellow]Error fetching lyrics from Lyrics.ovh: {str(e)}[/yellow]")
            return None, None
    
    def download_song(self, url_or_id, metadata=None, output_dir=None):
        """Download a song with the given metadata"""
        # Check if input is a number (index from search results)
        try:
            if isinstance(url_or_id, str) and url_or_id.isdigit():
                index = int(url_or_id) - 1  # Convert from 1-based to 0-based indexing
                
                if not self.last_search_results:
                    self.console.print("[red]No search results available. Please search first with 'search' command.[/red]")
                    return False
                
                if index < 0 or index >= len(self.last_search_results):
                    self.console.print(f"[red]Invalid index {index+1}. Available range: 1-{len(self.last_search_results)}[/red]")
                    return False
                    
                # Get the video from search results
                video = self.last_search_results[index]
                self.console.print(f"[green]Selected: {video['title']} by {video['channel']}[/green]")
                url_or_id = video["webpage_url"]
                
                # If no metadata provided, extract some info from the video title
                if not metadata:
                    metadata = {}
                    title_parts = video["title"].split(" - ")
                    
                    if len(title_parts) > 1:
                        artist = title_parts[0].strip()
                        title = " - ".join(title_parts[1:]).strip()
                        title = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', title).strip()
                    else:
                        artist = video["channel"]
                        title = title_parts[0].strip()
                        title = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', title).strip()
                        parts = re.split(r'\s+by\s+', title, flags=re.IGNORECASE)
                        if len(parts) > 1:
                            title = parts[0].strip()
                            artist = parts[1].strip()
                    
                    metadata['artist'] = artist
                    metadata['title'] = title
                    
                    # Get enhanced metadata like in the GUI
                    self.console.print(f"[bold blue]Fetching metadata for:[/bold blue] {artist} - {title}")
                    enhanced_metadata = self.get_metadata(artist, title)
                    
                    # Merge with the metadata we already have
                    for key, value in enhanced_metadata.items():
                        if key not in ['artist', 'title'] or not metadata.get(key):
                            metadata[key] = value
        except ValueError:
            # Not a number, continue with URL or ID
            pass
        
        if not url_or_id:
            self.console.print("[red]No URL or video ID provided[/red]")
            return False
            
        if not output_dir:
            output_dir = self.library_location
            
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                self.console.print(f"[red]Could not create output directory: {str(e)}[/red]")
                return False
                
        # If just an ID is provided, construct the URL
        if not url_or_id.startswith(('http://', 'https://')):
            url_or_id = f"https://www.youtube.com/watch?v={url_or_id}"
        
        self.console.print(f"[bold blue]Downloading from:[/bold blue] {url_or_id}")
        
        # If no metadata provided, extract some basic info from the video
        if not metadata:
            metadata = {}
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(url_or_id, download=False)
                    title_parts = info['title'].split(" - ")
                    
                    if len(title_parts) > 1:
                        metadata["artist"] = title_parts[0].strip()
                        metadata["title"] = " - ".join(title_parts[1:]).strip()
                        metadata["title"] = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', metadata["title"]).strip()
                    else:
                        metadata["artist"] = info.get('uploader', 'Unknown')
                        metadata["title"] = title_parts[0].strip()
                        metadata["title"] = re.sub(r'\(.*?\)|\[.*?\]|Official Video|Lyrics', '', metadata["title"]).strip()
                
                # Fetch additional metadata just like in the GUI
                artist = metadata.get("artist", "")
                title = metadata.get("title", "")
                if artist and title:
                    self.console.print(f"[bold blue]Fetching metadata for:[/bold blue] {artist} - {title}")
                    enhanced_metadata = self.get_metadata(artist, title)
                    
                    # Merge with the metadata we already have
                    for key, value in enhanced_metadata.items():
                        if key not in ['artist', 'title'] or not metadata.get(key):
                            metadata[key] = value
                    
            except Exception as e:
                self.console.print(f"[yellow]Could not extract video info: {str(e)}[/yellow]")
                metadata["artist"] = "Unknown"
                metadata["title"] = "Unknown"
        
        # Create a valid filename
        valid_filename = f"{metadata.get('artist', 'Unknown')} - {metadata.get('title', 'Unknown')}"
        valid_filename = valid_filename.replace("/", "-").replace("\\", "-").replace(":", "-").replace("?", "").replace('"', "")
        save_path = os.path.join(output_dir, f"{valid_filename}.mp3")
        
        # Download the song
        with Progress() as progress:
            download_task = progress.add_task("[green]Downloading...", total=100)
            
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_filename = os.path.join(temp_dir, "audio")
                    
                    def progress_hook(d):
                        if d['status'] == 'downloading':
                            p = d.get('_percent_str', '0%').replace('%', '')
                            try:
                                progress.update(download_task, completed=float(p))
                            except:
                                pass
                    
                    # Configure yt-dlp options
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': temp_filename,
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'quiet': True,
                        'no_warnings': True,
                        'progress_hooks': [progress_hook]
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url_or_id])
                    
                    downloaded_file = temp_filename + ".mp3"
                    if os.path.exists(downloaded_file):
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        
                        shutil.copy2(downloaded_file, save_path)
                        
                        # Set metadata in the MP3 file
                        progress.update(download_task, description="[yellow]Setting metadata...")
                        self._set_metadata(save_path, metadata)
                        
                        progress.update(download_task, completed=100, description="[bold green]Download complete!")
                        self.console.print(f"\n[bold green]Success![/bold green] File saved to: {save_path}")
                        return True
                    else:
                        self.console.print("[red]Error: Downloaded file not found[/red]")
                        return False
            
            except Exception as e:
                self.console.print(f"\n[bold red]Download failed:[/bold red] {str(e)}")
                return False
    
    def _set_metadata(self, file_path, metadata):
        """Set ID3 metadata for the downloaded MP3 file"""
        try:
            # First delete existing tags
            try:
                audio = MP3(file_path)
                audio.delete()
                audio.save()
            except Exception:
                pass
            
            tags = ID3()
            
            # Set title
            if metadata.get('title'):
                tags.add(TIT2(encoding=3, text=metadata['title']))
            
            # Set artist
            if metadata.get('artist'):
                tags.add(TPE1(encoding=3, text=metadata['artist']))
            
            # Set album
            if metadata.get('album'):
                tags.add(TALB(encoding=3, text=metadata['album']))
            
            # Set year
            if metadata.get('year'):
                tags.add(TDRC(encoding=3, text=metadata['year']))
            
            # Set genre
            if metadata.get('genre'):
                tags.add(TCON(encoding=3, text=metadata['genre']))
                
            # Set track number
            if metadata.get('track_number'):
                tags.add(TRCK(encoding=3, text=metadata['track_number']))
            
            # Add lyrics if provided
            if metadata.get('lyrics'):
                tags.add(USLT(
                    encoding=3,  # UTF-8
                    lang='eng',  # Language code (English)
                    desc='',     # Description
                    text=metadata['lyrics']
                ))
            
            # Add album art if we have a URL
            if metadata.get('artwork_url'):
                try:
                    response = requests.get(metadata['artwork_url'])
                    if response.status_code == 200:
                        tags.add(APIC(
                            encoding=3,  # UTF-8
                            mime='image/jpeg',
                            type=3,  # Cover image
                            desc='Cover',
                            data=response.content
                        ))
                except Exception as e:
                    self.console.print(f"[yellow]Error setting album art: {str(e)}[/yellow]")
            
            # Save the tags to the file
            tags.save(file_path)
            return True
                
        except Exception as e:
            self.console.print(f"[red]Error setting metadata: {str(e)}[/red]")
            return False

    def set_library_location(self, path):
        """Set the library location"""
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception as e:
                self.console.print(f"[red]Could not create directory: {str(e)}[/red]")
                return False
        
        self.library_location = path
        self.save_settings()
        self.console.print(f"[green]Library location set to:[/green] {path}")
        return True

def parse_arguments():
    parser = argparse.ArgumentParser(description='Music Library Extender - Download music from YouTube with proper metadata')
    parser.add_argument('--cli', action='store_true', help='Run in CLI mode instead of GUI')
    subparsers = parser.add_subparsers(dest='command', help='CLI commands')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search for songs')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--limit', type=int, default=10, help='Maximum number of results (default: 10)')
    search_parser.add_argument('--json', action='store_true', help='Output results as JSON')

    # Download command
    download_parser = subparsers.add_parser('download', help='Download a song')
    download_parser.add_argument('url_or_id', help='YouTube URL, video ID, or result number (1-based) from the last search')
    download_parser.add_argument('--output-dir', '-o', help='Output directory (default: library location from settings)')
    download_parser.add_argument('--artist', help='Artist name (optional, will be auto-detected)')
    download_parser.add_argument('--title', help='Song title (optional, will be auto-detected)')
    download_parser.add_argument('--album', help='Album name (optional, will be auto-detected)')
    download_parser.add_argument('--year', help='Release year (optional, will be auto-detected)')
    download_parser.add_argument('--genre', help='Genre (optional, will be auto-detected)')
    download_parser.add_argument('--track', help='Track number (optional, will be auto-detected)')
    download_parser.add_argument('--skip-metadata', action='store_true', help='Skip automatic metadata lookup')

    # Metadata command
    metadata_parser = subparsers.add_parser('metadata', help='Look up metadata without downloading')
    metadata_parser.add_argument('artist', help='Artist name')
    metadata_parser.add_argument('title', help='Song title')

    # Library command
    library_parser = subparsers.add_parser('library', help='Set library location')
    library_parser.add_argument('path', help='Path to music library')

    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    if args.cli:
        # CLI mode
        cli_handler = CLIHandler()
        
        if args.command == 'search':
            cli_handler.search_videos(args.query, limit=args.limit, json_output=args.json)
        
        elif args.command == 'download':
            metadata = {}
            if args.artist:
                metadata['artist'] = args.artist
            if args.title:
                metadata['title'] = args.title
            if args.album:
                metadata['album'] = args.album
            if args.year:
                metadata['year'] = args.year
            if args.genre:
                metadata['genre'] = args.genre
            if args.track:
                metadata['track_number'] = args.track
                
            # If we have artist and title but not other metadata, and auto metadata is not disabled
            if not args.skip_metadata and args.artist and args.title and not (args.album or args.year or args.genre):
                console = Console()
                console.print("[yellow]No complete metadata provided. Fetching from online sources...[/yellow]")
                fetched_metadata = cli_handler.get_metadata(args.artist, args.title)
                
                # Update with fetched metadata but keep user-provided values
                for key, value in fetched_metadata.items():
                    if key not in ['artist', 'title'] and value and key not in metadata:
                        metadata[key] = value
            
            cli_handler.download_song(args.url_or_id, metadata, args.output_dir)
        
        elif args.command == 'metadata':
            cli_handler.get_metadata(args.artist, args.title)
        
        elif args.command == 'library':
            cli_handler.set_library_location(args.path)
        
        else:
            console = Console()
            console.print("[red]Please specify a command. Use --help for options.[/red]")
            sys.exit(1)
    else:
        # GUI mode
        root = tk.Tk()
        app = MusicLibraryExtender(root)
        root.mainloop()