import os
import shutil
import json

import RNS

class ThemeManager:
    def __init__(self, config_file="server_config.json", theme_folder="themes", default_theme="default"):
        self.config_file = config_file
        self.theme_folder = theme_folder
        self.default_theme = default_theme
        self.selected_theme = None
        self.theme_files = {}

    def load_config(self):
        """
        Load the configuration file to get the selected theme.
        """
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding="utf-8") as file:
                config = json.load(file)
                self.selected_theme = config.get("theme", self.default_theme)
        else:
            self.selected_theme = self.default_theme

    def load_theme(self):
        """
        Load theme files based on the selected theme.
        """
        theme_path = os.path.join(self.theme_folder, self.selected_theme)

        if not os.path.exists(theme_path):
            RNS.log(f"[ERROR] Theme {self.selected_theme} not found, using default theme.", RNS.LOG_ERROR)
            theme_path = os.path.join(self.theme_folder, self.default_theme)

        theme_files = {}
        for filename in os.listdir(theme_path):
            file_path = os.path.join(theme_path, filename)
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as file:
                    theme_files[filename] = file.read().strip()

        self.theme_files = theme_files

    def apply_theme(self, server):
        """
        Apply the loaded theme files to the server.
        :param server: The server to apply the theme to.
        """
        welcome_message = self.theme_files.get("welcome_message.txt", "Welcome to the RetiBBS Server!")
        main_menu_message = self.theme_files.get("main_menu.txt", "Main Menu: [?] Help [h] Hello [n] Name [b] Boards Area [lo] Log Out")
        boards_menu_message = self.theme_files.get("boards_menu.txt", "Boards Menu: [?] Help [b] Back [lb] List Boards [cb] Change Board [p] Post Message [lm] List Messages")

        server.welcome_message = welcome_message
        server.main_menu_message = main_menu_message
        server.boards_menu_message = boards_menu_message

        return welcome_message
