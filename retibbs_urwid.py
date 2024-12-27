#!/usr/bin/env python3
import argparse
import os
import queue
import re
import sys
import time
import urwid

import RNS

APP_NAME = "retibbs"
SERVICE_NAME = "bbs"

server_link = None
client_identity = None
ui_ref = None

message_queue = queue.Queue()
announcement_queue = queue.Queue()

_old_log = RNS.log

def urwid_log_hook(message, level=RNS.LOG_INFO, end="\n"):
    """
    Override RNS.log so all logs go into our TUI message queue.
    You can skip this if you only want to display server messages, not logs.
    """
    message_queue.put(f"[LOG] {message}")
    # If you also want them in original stdout logs, call the old logger:
    # _old_log(message, level=level)

# Uncomment if you want to redirect *all* logs into the TUI:
# RNS.log = urwid_log_hook


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
        # Convert the destination hash to a readable format
        dest_hash_str = RNS.prettyhexrep(destination_hash)
        
        # Decode the app_data if present
        app_data_str = app_data.decode("utf-8", "ignore") if app_data else "No App Data"
        
        # Format the announce message
        #announce_message = f"[ANNOUNCE] From {dest_hash_str}: {app_data_str}"
        announce_message = f"{dest_hash_str}:\n {app_data_str}"
        
        # Enqueue the announce message to the announcement_queue
        announcement_queue.put(announce_message)
        
        # OPTIONAL: Log the announce
        #RNS.log(f"[ANNOUNCE HANDLER] Received announce: {announce_message}")

def register_announce_handler():
    """
    Registers the announce handler with Reticulum's transport.
    """
    # Initialize the announce handler with an aspect filter if needed
    # For example, to filter announces from a specific application aspect:
    # aspect_filter = "example_utilities.announcesample.fruits"
    #aspect_filter = None  # Set to None to accept all announces
    aspect_filter = aspect_filter="retibbs.bbs"

    announce_handler = AnnounceHandler(aspect_filter=aspect_filter)
    
    # Register the announce handler
    RNS.Transport.register_announce_handler(announce_handler)
    
    RNS.log("[CLIENT] Announce handler registered.")

def client_setup(server_hexhash, configpath, identity_file):
    """
    Initializes Reticulum, sets up the client Identity,
    forms a Link to the server, and starts the urwid UI.
    """
    global client_identity

    reticulum = RNS.Reticulum(configpath)

    client_identity = load_or_create_identity(identity_file)
    RNS.log("[CLIENT] Using Identity: " + str(client_identity))

    try:
        server_addr = bytes.fromhex(server_hexhash)
    except ValueError:
        RNS.log("[CLIENT] Invalid server hexhash!")
        sys.exit(1)

    if not RNS.Transport.has_path(server_addr):
        RNS.log("[CLIENT] Path to server unknown, requesting path and waiting for announce...")
        RNS.Transport.request_path(server_addr)
        timeout_t0 = time.time()
        while not RNS.Transport.has_path(server_addr):
            if time.time() - timeout_t0 > 15:
                RNS.log("[CLIENT] Timed out waiting for path!")
                sys.exit(1)
            time.sleep(0.1)

    server_identity = RNS.Identity.recall(server_addr)
    if not server_identity:
        RNS.log("[CLIENT] Could not recall server Identity!")
        sys.exit(1)

    server_destination = RNS.Destination(
        server_identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        APP_NAME,
        SERVICE_NAME,
        "client"
    )

    link = RNS.Link(server_destination)
    link.set_link_established_callback(link_established)
    link.set_link_closed_callback(link_closed)
    link.set_packet_callback(client_packet_received)

    # IMPORTANT: Accept resources from the server
    link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
    link.set_resource_started_callback(resource_started_callback)
    link.set_resource_concluded_callback(resource_concluded_callback)

    # Register the announce handler
    register_announce_handler()

    RNS.log("[CLIENT] Establishing link with server...")

    wait_for_link(link)

def wait_for_link(link):
    t0 = time.time()
    while link.status not in [RNS.Link.ACTIVE, RNS.Link.CLOSED]:
        if time.time() - t0 > 10:
            RNS.log("[CLIENT] Timeout waiting for link to establish.")
            link.teardown()
            sys.exit(1)
        time.sleep(0.1)

    if link.status == RNS.Link.ACTIVE:
        RNS.log("[CLIENT] Link is ACTIVE. Now identifying to server...")
        link.identify(client_identity)

        # Instead of a blocking loop, we now start the TUI.
        start_urwid_ui(link)
    else:
        RNS.log("[CLIENT] Link could not be established (status=CLOSED).")
        sys.exit(1)

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
    #pass
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

def link_closed(link):
    RNS.log("\n[CLIENT] Link was closed or lost. Exiting.")
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

class BBSClientUI:
    def __init__(self, link):
        self.link = link
        self.receiving_data = False
        self.current_board = "None"

        # Initialize message walker and listbox
        self.message_walker = urwid.SimpleListWalker([])
        self.message_listbox = urwid.ListBox(self.message_walker)
        self.message_listbox_box = urwid.LineBox(
            self.message_listbox,
            # Optional: Add a title or other decorations
        )

        # Initialize message walker and listbox for announcements
        self.announcement_walker = urwid.SimpleListWalker([])
        self.announcement_listbox = urwid.ListBox(self.announcement_walker)
        self.announcement_listbox_box = urwid.LineBox(
            self.announcement_listbox,
            title="Announces",
            title_align='left'
        )

        # Define the command prompt text
        self.prompt_text = f"Command [Board: {self.current_board}]"
        self.command_title = urwid.Text(self.prompt_text)

        # Define the input prompt and edit box
        self.input_prompt = urwid.Text("> ")
        self.input_edit = urwid.Edit()

        # Combine the input prompt and edit box into columns
        self.input_edit_box = urwid.Columns([
            ('fixed', len("> "), self.input_prompt),
            ('weight', 1, self.input_edit)
        ], dividechars=1, min_width=1)

        # Create a Pile to stack the command prompt and input field vertically
        self.input_pile = urwid.Pile([
            self.command_title,
            self.input_edit_box
        ])

        # Create a LineBox for the footer containing the input pile
        self.footer = urwid.LineBox(
            self.input_pile,
            title=None 
        )

        # Assemble the body with messages and announcements side by side
        self.body = urwid.Columns([
            ('weight', 3, self.message_listbox_box),
            ('weight', 1, self.announcement_listbox_box)
        ], dividechars=1, min_width=40)

        # Assemble the frame with header, body, and footer
        self.frame = urwid.Frame(
            header=urwid.Text("- RetiBBS -", align='center'),
            body=urwid.Pile([
                self.body
            ]),
            footer=self.footer
        )

        # Initialize the MainLoop
        self.loop = urwid.MainLoop(
            self.frame,
            palette=[
                ('reversed', 'standout', ''),
                ('announcement', 'dark cyan', ''),
                ('error', 'dark red', ''),
                # Add more styles as needed
            ],
            unhandled_input=self.handle_input
        )

        # Set up periodic polling of the message queue
        self.loop.set_alarm_in(0.1, self.poll_message_queues)

        # Display initial usage instructions
        self.show_usage_instructions()

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

    def set_current_board(self, board_name):
        """
        Update the current board and modify the command title.
        """
        self.current_board = board_name
        self.prompt_text = f"Command [Board: {self.current_board}]"
        self.command_title.set_text(self.prompt_text)

    def run(self):
        self.loop.run()

    def handle_input(self, key):
        if self.receiving_data:
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

            data = user_command.encode("utf-8")
            if len(data) <= RNS.Link.MDU:
                RNS.Packet(self.link, data).send()
                self.add_line(f"> {user_command}")
            else:
                self.add_line(f"[ERROR] Data size {len(data)} exceeds MDU!")
        elif key in ("ctrl c",):
            self.tear_down()

    def poll_message_queues(self, loop, user_data):
        while not message_queue.empty():
            msg = message_queue.get_nowait()
            self.add_line(msg)
        while not announcement_queue.empty():
            ann = announcement_queue.get_nowait()
            self.add_announcement(ann)
        loop.set_alarm_in(0.1, self.poll_message_queues)

    def add_line(self, text):
        self.message_walker.append(urwid.Text(text))
        self.message_listbox.focus_position = len(self.message_walker) - 1
    
    def add_announcement(self, text):
        # Format announcements differently, e.g., with a prefix or different color
        formatted_ann = urwid.Text(('announcement', text))
        self.announcement_walker.append(formatted_ann)
        self.announcement_listbox.focus_position = len(self.announcement_walker) - 1

    def show_usage_instructions(self):
        """
        Print usage instructions for the user.
        """
        self.add_line("Client Ready!")
        self.add_line("  ? | help to show command help")
        self.add_line("  quit with 'q', 'quit', 'e', or 'exit'")

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
            required=True,
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
        client_setup(args.server, args.config, args.identity_file)

    except KeyboardInterrupt:
        print("")
        exit()
