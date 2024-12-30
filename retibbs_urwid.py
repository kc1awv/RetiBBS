#!/usr/bin/env python3
import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import urwid

import RNS

APP_NAME = "retibbs"
SERVICE_NAME = "bbs"

reticulum_instance = None
server_link = None
client_identity = None
ui_ref = None

log_queue = queue.Queue()
message_queue = queue.Queue()
announcement_queue = queue.Queue()

_old_log = RNS.log

def urwid_log_hook(message, level=RNS.LOG_INFO, end="\n"):
    """
    Override RNS.log so all logs go into the log_queue for the logs tab.
    """
    severity = {RNS.LOG_INFO: "INFO", RNS.LOG_WARNING: "WARNING", RNS.LOG_ERROR: "ERROR"}.get(level, "INFO")
    log_queue.put(f"[{severity}] {message}")
    # If you also want them in original stdout logs, call the old logger:
    # _old_log(message, level=level)

RNS.log = urwid_log_hook

def load_or_create_identity(identity_path):
    if os.path.isfile(identity_path):
        identity = RNS.Identity.from_file(identity_path)
        RNS.log(f"[CLIENT] Loaded Identity from {identity_path}")
    else:
        identity = RNS.Identity()
        identity.to_file(identity_path)
        RNS.log(f"[CLIENT] Created new Identity and saved to {identity_path}")
    return identity

class AnnounceHandler:
    def __init__(self, aspect_filter=None):
        """
        Initialize the Announce Handler.
        
        Args:
            aspect_filter (str, optional): Specific aspect to filter announces.
                If None, all announces are processed.
        """
        self.aspect_filter = aspect_filter

    def received_announce(self, destination_hash, announced_identity, app_data):
        """
        Callback method invoked when an announce matching the filter is received.
        
        Args:
            destination_hash (bytes): Hash of the announcing destination.
            announced_identity (RNS.Identity): Identity of the announcing destination.
            app_data (bytes): Application-specific data included in the announce.
        """
        dest_hash_raw = destination_hash.hex()
        dest_hash_display = RNS.prettyhexrep(destination_hash)
        display_name = dest_hash_display
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        if app_data:
            try:
                app_data_json = json.loads(app_data.decode("utf-8"))
                if "server_name" in app_data_json:
                    display_name = app_data_json["server_name"]
                elif "client_name" in app_data_json:
                    display_name = app_data_json["client_name"]
            except json.JSONDecodeError:
                pass
        
        announce_message = {
            "display_name": display_name,
            "dest_hash": dest_hash_raw,
            "timestamp": timestamp
        }
        
        announcement_queue.put(announce_message)

        if ui_ref is not None:
            ui_ref.add_announcement(announce_message)
        
        # OPTIONAL: Log the announce
        #RNS.log(f"[ANNOUNCE HANDLER] Received announce: {announce_message}")

def register_announce_handler():
    """
    Registers the announce handler with Reticulum's transport.
    """
    aspect_filter = "retibbs.bbs"
    announce_handler = AnnounceHandler(aspect_filter=aspect_filter)
    RNS.Transport.register_announce_handler(announce_handler)
    RNS.log("[CLIENT] Announce handler registered.")

def initialize_reticulum(configpath, identity_file):
    """
    Initializes Reticulum and loads or creates the client identity.
    
    Args:
        configpath (str): Path to Reticulum configuration directory.
        identity_file (str): Path to the client identity file.
    
    Returns:
        RNS.Reticulum: The initialized Reticulum instance.
    """
    global reticulum_instance, client_identity

    if reticulum_instance is not None:
        RNS.log("[CLIENT] Reticulum is already initialized.")
        return reticulum_instance

    reticulum_instance = RNS.Reticulum(configpath)
    client_identity = load_or_create_identity(identity_file)
    RNS.log(f"[CLIENT] Using Identity: {client_identity}")
    
    return reticulum_instance

def client_setup(server_hexhash, configpath, identity_file):
    """
    Initializes Reticulum, sets up the client Identity,
    forms a Link to the server if server_hexhash is provided,
    and starts the urwid UI.
    """
    initialize_reticulum(configpath, identity_file)

    global ui_ref
    ui = BBSClientUI()
    ui_ref = ui
    ui.set_current_board(board_name="No Link")

    if server_hexhash:
        connection_thread = threading.Thread(target=connect_client, args=(server_hexhash,), daemon=True)
        connection_thread.start()
    else:
        register_announce_handler()
    
    ui.run()

def connect_client(server_hexhash):
    """
    Connects to a specified server using its hexhash.
    
    Args:
        server_hexhash (str): The hexhash of the server to connect to.
    """
    try:
        server_addr = bytes.fromhex(server_hexhash)
    except ValueError:
        RNS.log(f"[CLIENT] Invalid server hexhash! {server_hexhash}")
        message_queue.put("[CONNECT] Failed: Invalid server hexhash.")
        return

    try:
        if not RNS.Transport.has_path(server_addr):
            RNS.log("[CLIENT] Path to server unknown, requesting path and waiting for announce...")
            RNS.Transport.request_path(server_addr)
            timeout_t0 = time.time()
            while not RNS.Transport.has_path(server_addr):
                if time.time() - timeout_t0 > 15:
                    RNS.log("[CLIENT] Timed out waiting for path!")
                    message_queue.put("[CONNECT] Failed: Timed out waiting for path.")
                    return
                time.sleep(0.1)

        server_identity = RNS.Identity.recall(server_addr)
        if not server_identity:
            RNS.log("[CLIENT] Could not recall server Identity!")
            message_queue.put("[CONNECT] Failed: Could not recall server Identity.")
            return

        server_destination = RNS.Destination(
            server_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            APP_NAME,
            SERVICE_NAME
        )

        link = RNS.Link(server_destination)
        link.set_link_established_callback(link_established)
        link.set_link_closed_callback(link_closed)
        link.set_packet_callback(client_packet_received)

        # IMPORTANT: Accept resources from the server
        link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
        link.set_resource_started_callback(resource_started_callback)
        link.set_resource_concluded_callback(resource_concluded_callback)

        register_announce_handler()

        RNS.log("[CLIENT] Establishing link with server...")
        message_queue.put("[CONNECT] Establishing link with server...")

        wait_for_link(link)

        if link.status == RNS.Link.ACTIVE:
            RNS.log("[CLIENT] Link is ACTIVE. Now identifying to server...")
            message_queue.put("[CONNECT] Link is ACTIVE. Now identifying to server...")
            link.identify(client_identity)
            RNS.log("[CLIENT] Successfully connected to the server.")
            message_queue.put("[CONNECT] success")
            message_queue.put(("SET_LINK", link))
        else:
            RNS.log("[CLIENT] Link could not be established (status=CLOSED).")
            message_queue.put("[CONNECT] Failed: Link could not be established.")
            sys.exit(1)

    except Exception as e:
        RNS.log(f"[CLIENT] Error connecting to server: {e}", RNS.LOG_ERROR)
        message_queue.put("[CONNECT] Failed: Error connecting to server.")

def wait_for_link(link):
    t0 = time.time()
    while link.status not in [RNS.Link.ACTIVE, RNS.Link.CLOSED]:
        if time.time() - t0 > 10:
            RNS.log("[CLIENT] Timeout waiting for link to establish.")
            link.teardown()
            sys.exit(1)
        time.sleep(0.1)

def client_packet_received(message_bytes, packet):
    """
    Called when the server sends data over the link.
    We'll enqueue this for display in the TUI.
    """
    text = message_bytes.decode("utf-8", "ignore")
    message_queue.put("[SERVER-PACKET]\n" + text)

    match = re.search(r"You have joined board '(.+)'", text)
    if match:
        board_name = match.group(1)
        if ui_ref is not None:
            ui_ref.set_current_board(board_name)
    elif "You are not in any board." in text:
        if ui_ref is not None:
            ui_ref.set_current_board("None")

def resource_started_callback(resource):
    """
    Optional: Called when the server begins sending a resource.
    You could display a 'downloading...' message or track progress.
    """
    global ui_ref
    if ui_ref is not None:
        ui_ref.set_receiving_data(True)

def resource_concluded_callback(resource):
    """
    Called when the resource is fully transferred.
    We decode the data and display it in the TUI.
    """
    global ui_ref
    if ui_ref is not None:
        ui_ref.set_receiving_data(False)
    if resource.data is not None:
        fileobj = resource.data
        fileobj.seek(0)
        data = fileobj.read()
        text = data.decode("utf-8", "ignore")
        message_queue.put("[SERVER-RESOURCE]\n" + text)

        match = re.search(r"You have joined board '(.+)'", text)
        if match:
            board_name = match.group(1)
            if ui_ref is not None:
                ui_ref.set_current_board(board_name)
    else:
        message_queue.put("[SERVER-RESOURCE] Transfer concluded, but no data received!")

def link_established(link):
    RNS.log("[CLIENT] link_established callback, link is ready.")
    global server_link
    server_link = link

def link_closed(self, link):
    RNS.log("\n\n[CLIENT] Link was closed or lost. Exiting.")
    self.link = None
    self.set_current_board()
    RNS.Reticulum.exit_handler()
    time.sleep(1)
    sys.exit(0)

def start_urwid_ui(link):
    """
    Build and run the urwid-based TUI. 
    'link' is our active RNS.Link to the server.
    """
    global ui_ref
    ui = BBSClientUI(link)
    ui_ref = ui
    ui.run()

class TabBar(urwid.WidgetWrap):
    def __init__(self, tabs, on_tab_change):
        self.tabs = tabs
        self.on_tab_change = on_tab_change
        self.current_tab = 0

        tab_buttons = []
        for idx, tab in enumerate(tabs):
            button = urwid.Button(tab)
            urwid.connect_signal(button, 'click', self.tab_clicked, user_args=[idx])
            if idx == self.current_tab:
                button = urwid.AttrMap(button, 'button select', 'reversed')
            else:
                button = urwid.AttrMap(button, 'button normal', 'button select')
            tab_buttons.append(button)
        
        self.tabs_box = urwid.Columns(tab_buttons)
        self.widget = self.tabs_box
        super().__init__(self.widget)

    def tab_clicked(self, idx, button):
        self.current_tab = idx
        self.update_tabs()
        self.on_tab_change(idx)

    def update_tabs(self):
        new_buttons = []
        for idx, tab in enumerate(self.tabs):
            button = urwid.Button(tab)
            urwid.connect_signal(button, 'click', self.tab_clicked, user_args=[idx])
            if idx == self.current_tab:
                button = urwid.AttrMap(button, 'button select', 'reversed')
            else:
                button = urwid.AttrMap(button, 'button normal', 'button select')
            new_buttons.append(button)
        self.tabs_box.contents = [(new_buttons[i], self.tabs_box.options()) for i in range(len(new_buttons))]
        self.tabs_box = urwid.Columns(new_buttons)
        self.widget = self.tabs_box
        self._invalidate()

class BBSClientUI:
    def __init__(self, link=None):
        self.link = link
        self.receiving_data = False
        self.current_board = "None"
        self.announcements = {}
        self.modal = None
        self.active_tab = 'Main'
        
        self.title = urwid.Text(" - RetiBBS Client - ", align='center')

        self.tabs = ['Main', 'Logs']
        self.tab_bar = TabBar(self.tabs, self.on_tab_change)

        self.header = urwid.Pile([
            self.title,
            self.tab_bar
        ])
        
        self.message_walker = urwid.SimpleListWalker([])
        self.message_listbox = urwid.ListBox(self.message_walker)
        self.message_listbox_box = urwid.LineBox(
            self.message_listbox,
            title="Messages",
            title_align='left'
        )

        self.announcement_walker = urwid.SimpleListWalker([])
        self.announcement_listbox = urwid.ListBox(self.announcement_walker)
        self.announcement_listbox_box = urwid.LineBox(
            self.announcement_listbox,
            title="Announces",
            title_align='left'
        )

        self.log_walker = urwid.SimpleListWalker([])  # Walker for logs
        self.log_listbox = urwid.ListBox(self.log_walker)
        self.log_listbox_box = urwid.LineBox(
            self.log_listbox,
            title="Logs",
            title_align='left'
        )

        self.prompt_text = f"Command [Board: {self.current_board}]"
        self.command_title = urwid.Text(self.prompt_text)

        self.input_prompt = urwid.Text(">")
        self.input_edit = urwid.Edit()

        self.input_edit_box = urwid.Columns([
            ('fixed', len(">"), self.input_prompt),
            ('weight', 1, self.input_edit)
        ], dividechars=1, min_width=1)

        self.input_pile = urwid.Pile([
            self.command_title,
            self.input_edit_box
        ])

        self.footer = urwid.LineBox(
            self.input_pile,
            title=None 
        )

        self.main_body = urwid.Columns([
            ('weight', 3, self.message_listbox_box),
            ('weight', 1, self.announcement_listbox_box)
        ], dividechars=1, min_width=40)

        self.logs_body = self.log_listbox_box

        self.body = self.main_body

        self.frame = urwid.Frame(
            header=self.header,
            body=self.body,
            footer=self.footer
        )

        self.loop = urwid.MainLoop(
            self.frame,
            palette=[
                ('reversed', 'standout', ''),
                ('announcement', 'dark cyan', ''),
                ('error', 'dark red', ''),
                ('button normal', 'light gray', ''),
                ('button select', 'white', 'dark blue'),
                ('modal', 'white', 'dark gray'),
                # Add more styles as needed
            ],
            unhandled_input=self.handle_input
        )

        self.loop.set_alarm_in(0.1, self.poll_queues)

        self.show_usage_instructions()
    
    def on_tab_change(self, idx):
        """
        Callback when a tab is changed.
        """
        selected_tab = self.tabs[idx]
        self.active_tab = selected_tab
        if selected_tab == 'Main':
            self.frame.body = self.main_body
            self.frame.footer = self.footer
        elif selected_tab == 'Logs':
            self.frame.body = self.logs_body
            self.frame.footer = None
    
    def set_link(self, link):
        """
        Sets the link after it's established.
        """
        self.link = link
        self.add_line("[CLIENT] Link established and set in UI.")
        self.set_current_board()

    def set_receiving_data(self, is_receiving):
        """
        Called from resource_started_callback / resource_concluded_callback
        to show or hide 'Receiving Data...' and block user input.
        """
        self.receiving_data = is_receiving
        if is_receiving:
            self.input_edit.set_edit_text("Receiving Data...")
            self.input_edit.set_edit_pos(len("Receiving Data..."))
        else:
            self.input_edit.set_edit_text("")
            self.input_edit.set_edit_pos(0)

    def set_current_board(self, board_name=None):
        """
        Update the current board and modify the command title.
        """
        if self.link:
            self.current_board = board_name if board_name else "None"
            self.prompt_text = f"Command [Board: {self.current_board}]"
        else:
            self.prompt_text = "Command [No Link]"
        self.command_title.set_text(self.prompt_text)

    def run(self):
        self.loop.run()

    def handle_input(self, key):
        if self.receiving_data:
            return

        if self.modal:
            if key in ("esc", "ctrl c"):
                self.close_modal()
            return

        if key in ("enter", "shift enter"):
            user_command = self.input_edit.edit_text.strip()
            self.input_edit.set_edit_text("")
            if not user_command:
                return

            cmd_lower = user_command.lower()
            if cmd_lower in ["q", "quit", "e", "exit"]:
                self.add_line("[CLIENT] Exiting.")
                self.tear_down()
                return

            if cmd_lower in ["?", "help"]:
                if self.link:
                    data = user_command.encode("utf-8")
                    if len(data) <= RNS.Link.MDU:
                        RNS.Packet(self.link, data).send()
                        self.add_line(f"> {user_command}")
                    else:
                        self.add_line(f"[ERROR] Data size {len(data)} exceeds MDU!")
                else:
                    self.show_usage_instructions()
                return

            if self.link:
                data = user_command.encode("utf-8")
                if len(data) <= RNS.Link.MDU:
                    RNS.Packet(self.link, data).send()
                    self.add_line(f"> {user_command}")
                else:
                    self.add_line(f"[ERROR] Data size {len(data)} exceeds MDU!")
            else:
                self.add_line("[CLIENT] No link established. Cannot send command.")
        elif key in ("ctrl c",):
            self.tear_down()

    def poll_queues(self, loop, user_data):
        while not message_queue.empty():
            msg = message_queue.get_nowait()
            if isinstance(msg, tuple) and msg[0] == "SET_LINK":
                link = msg[1]
                self.set_link(link)
                self.set_current_board()
            elif msg.startswith("[LOG]"):
                self.log_walker.append(urwid.Text(msg))
                self.log_listbox.focus_position = len(self.log_walker) - 1
            elif msg.startswith("[CONNECT]"):
                if "success" in msg.lower():
                    self.add_line("[CLIENT] Successfully connected to the server.")
                    self.set_current_board()
                elif "failed" in msg.lower():
                    self.add_line("[CLIENT] Failed to connect to the server.")
                    self.set_current_board()
                else:
                    self.add_line(msg)
                    self.set_current_board()
                self.close_modal()
            else:
                self.add_line(msg)
        while not log_queue.empty():
            log_msg = log_queue.get_nowait()
            self.log_walker.append(urwid.Text(log_msg))
            self.log_listbox.focus_position = len(self.log_walker) - 1
        while not announcement_queue.empty():
            ann = announcement_queue.get_nowait()
            self.add_announcement(ann)
        loop.set_alarm_in(0.1, self.poll_queues)

    def add_line(self, text):
        self.message_walker.append(urwid.Text(text))
        self.message_listbox.focus_position = len(self.message_walker) - 1

    def add_announcement(self, announce):
        """
        Adds an announcement to the Announcements pane as a clickable button.
        If an announce from the same dest_hash exists, update it instead.

        Args:
            announce (dict): Dictionary containing 'display_name', 'dest_hash', and 'timestamp'.
        """
        display_name = announce.get("display_name", "Unknown")
        dest_hash = announce.get("dest_hash", "Unknown")
        timestamp = announce.get("timestamp", "")

        if dest_hash in self.announcements:
            existing_ann = self.announcements[dest_hash]
            existing_ann['display_name'] = display_name
            existing_ann['timestamp'] = timestamp

            existing_ann['button'].original_widget.set_label(display_name)

            self.announcement_walker.remove(existing_ann['button'])
            self.announcement_walker.insert(0, existing_ann['button'])
            self.announcement_listbox.focus_position = 0

        else:
            button = urwid.Button(display_name)
            urwid.connect_signal(button, 'click', self.show_announce_modal, user_args=(display_name, dest_hash))
            button = urwid.AttrMap(button, 'button normal', focus_map='button select')

            self.announcement_walker.append(button)
            self.announcement_listbox.focus_position = len(self.announcement_walker) - 1

            self.announcements[dest_hash] = {
                'display_name': display_name,
                'dest_hash': dest_hash,
                'timestamp': timestamp,
                'button': button
            }

    def show_announce_modal(self, display_name, dest_hash, button):
        """
        Displays a modal with the announcement details.

        Args:
            button (urwid.Button): The button that was clicked.
            display_name (str): The display name extracted from the announce.
            dest_hash (str): The destination hash of the announcer.
        """
        timestamp = self.announcements.get(dest_hash, {}).get("timestamp", "Unknown")

        modal_content = [
            urwid.Text(f"Name: {display_name}", align='center'),
            urwid.Text(f"Destination Hash: {dest_hash}", align='center'),
            urwid.Text(f"Last Announce: {timestamp}", align='center'),
            urwid.Divider(),
            urwid.Button("Close", on_press=self.close_modal)
        ]

        connect_button = urwid.Button("Connect to Server")
        urwid.connect_signal(connect_button, 'click', self.connect_to_selected_server, user_args=(dest_hash,))
        modal_content.append(connect_button)

        pile = urwid.Pile(modal_content)
        fill = urwid.Filler(pile, valign='middle')
        box = urwid.LineBox(fill, title="Announce Details", title_align='center')
        overlay = urwid.Overlay(
            box,
            self.frame,
            align='center',
            width=('relative', 50),
            valign='middle',
            height=('relative', 40),
            min_width=20,
            min_height=9
        )

        self.modal = overlay
        self.loop.widget = self.modal
    
    def connect_to_selected_server(self, dest_hash, button):
        """
        Handle connecting to the server when the "Connect to Server" button is pressed.

        Args:
            button (urwid.Button): The button that was clicked.
            dest_hash (str): The destination hash of the server to connect to.
        """
        RNS.log(f"[CLIENT] Initiating connection to server with hash: {dest_hash}...")
        message_queue.put("[CLIENT] Initiating connection to server...")

        connection_thread = threading.Thread(target=connect_client, args=(dest_hash,))
        connection_thread.daemon = True
        connection_thread.start()

        self.close_modal(button)

    def close_modal(self, button=None):
        """
        Closes the currently open modal.
        """
        self.modal = None
        self.loop.widget = self.frame

    def show_usage_instructions(self):
        """
        Print usage instructions for the user.
        """
        usage_text = (
            "Client Ready!\n"
            "  ? | help to show command help\n"
            "  quit with 'q', 'quit', 'e', or 'exit'\n"
        )
        self.add_line(usage_text)

    def send_announce(self, destination, app_data_str):
        """
        Sends an announce with the specified app data.
        
        Args:
            destination (RNS.Destination): The destination to announce.
            app_data_str (str): The application-specific data to include.
        """
        try:
            announce_data = json.dumps({"client_name": app_data_str}).encode("utf-8")
            destination.announce(app_data=announce_data)
            self.add_line(f"[CLIENT] Sent announce: {app_data_str}")
            RNS.log(f"[CLIENT] Sent announce: {app_data_str}")
        except Exception as e:
            self.add_line(f"[ERROR] Failed to send announce: {e}")
            RNS.log(f"[CLIENT] Error sending announce: {e}", RNS.LOG_ERROR)

    def tear_down(self):
        if self.link is not None:
            self.link.teardown()
        self.loop.stop()
        RNS.Reticulum.exit_handler()
        time.sleep(1)
        sys.exit(0)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="RetiBBS Client")
        parser.add_argument(
            "--config",
            action="store",
            default=None,
            help="Path to alternative Reticulum config directory",
            type=str
        )
        parser.add_argument(
            "--server",
            action="store",
            default=None,
            help="Server hexhash to connect (e.g. e7a1f4d35b2a...)",
            type=str
        )
        parser.add_argument(
            "--identity-file",
            action="store",
            default="client_identity.pem",
            help="Path to store or load the client identity",
            type=str
        )

        args = parser.parse_args()
        if args.server:
            client_setup(args.server, args.config, args.identity_file)
        else:
            client_setup(None, args.config, args.identity_file)

    except KeyboardInterrupt:
        print("")
        exit()
