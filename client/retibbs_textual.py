import argparse
import asyncio
import json
import os
import re
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, TabbedContent, TabPane, Input, Log, DataTable, Static, Button, Label

import RNS

ADDRESS_BOOK_FILE = "address_book.json"

class AnnounceHandler:
    def __init__(self, app, aspect_filter=None):
        self.app = app
        self.aspect_filter = aspect_filter

    def received_announce(self, destination_hash, announced_identity, app_data):
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

        # OPTIONAL: Add to app log
        #self.app.write_debug_log(
        #    f"[ANNOUNCE] {timestamp} - {display_name} ({dest_hash_display})"
        #)

        self.app.on_announce(destination_hash, announced_identity, app_data)

class ServerDetailScreen(ModalScreen):
    """Screen to display server details."""

    def __init__(self, server_name, destination_hash, timestamp, on_connect, saved_in_address_book):
        super().__init__()
        self.server_name = server_name
        self.destination_hash = destination_hash
        self.timestamp = timestamp
        self.on_connect = on_connect
        self.saved_in_address_book = saved_in_address_book

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(
                f"Server Name: {self.server_name}\nDestination Hash: {self.destination_hash}\nLast Heard: {self.timestamp}", 
                id="server_details"
            ),
            Button("Connect", id="connect", variant="success", classes="button"),
            Button(
                "Remove from Address Book" if self.saved_in_address_book else "Save to Address Book",
                id="toggle_address_book",
                variant="primary",
                classes="button",
            ),
            Button("Close", id="close", variant="default", classes="button"),
            id="server_details_dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect":
            asyncio.create_task(self.on_connect(self.destination_hash))
            self.app.pop_screen()
        elif event.button.id == "toggle_address_book":
            self.app.pop_screen()
            self.app.toggle_address_book(self.destination_hash, self.saved_in_address_book)
        elif event.button.id == "close":
            self.app.pop_screen()

class RetiBBSClient(App):
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding(key="q", action="quit", description="Quit the app"),
        Binding(
            key="question_mark",
            action="show_help",
            description="Show help",
            key_display="?",
        )
    ]

    def __init__(self, server_hexhash=None):
        super().__init__()
        self._deferred_debug_log = []
        self.server_hexhash = server_hexhash
        self.client_identity = None
        self.link = None
        self.servers = {}
        self.address_book = {}
        self.active_tab = "servers"
        self.server_list_update_pending = False

    def compose(self) -> ComposeResult:
        yield Header()
        
        server_tab = TabPane(title="Servers", id="servers")
        server_tab.compose_add_child(
            DataTable(id="server_list", classes="server-list", cursor_type="row")
        )
        
        address_tab = TabPane(title="Address Book", id="address_book")
        address_tab.compose_add_child(
            DataTable(id="address_book", classes="address-book", cursor_type="row")
        )
        
        tabs = TabbedContent(id="tabs", classes="tabs")
        tabs.compose_add_child(server_tab)
        tabs.compose_add_child(address_tab)
        tabs.default_tab = "Servers"
        
        yield Horizontal(
            Vertical(
                Log(id="main_log"),
                Input(placeholder="Enter command...", id="command_input"),
                id="left_panel"
            ),
            Vertical(
                tabs,
                Log(id="debug_log", classes="debug-log"),
                id="right_panel"
            ),
            id="main_body"
        )
        yield Footer()
    
    def load_address_book(self):
        if os.path.exists(ADDRESS_BOOK_FILE):
            try:
                with open(ADDRESS_BOOK_FILE, "r") as file:
                    address_book = json.load(file)
                    self._deferred_debug_log.append(f"[DEBUG] Address book loaded: {address_book}")
                    return address_book
            except Exception as e:
                self._deferred_debug_log.append(f"[DEBUG] Error loading address book: {e}")
        return {}
    
    def save_address_book(self):
        with open(ADDRESS_BOOK_FILE, "w") as file:
            json.dump(self.address_book, file, indent=4)

    def write_debug_log(self, message):
        try:
            # Attempt to find the debug log and write the message
            debug_log = self.query_one("#debug_log", Log)
            debug_log.write_line(message)
        except Exception:
            # Defer the message if the debug log is not found
            if not hasattr(self, "_deferred_debug_log"):
                self._deferred_debug_log = []
            self._deferred_debug_log.append(message)
    
    def write_log(self, message):
        log = self.query_one("#main_log", Log)
        log.write_line(message)

    def load_or_create_identity(self, identity_path):
        if os.path.exists(identity_path):
            identity = RNS.Identity.from_file(identity_path)
            RNS.log(f"[INIT] Loaded existing identity from {identity_path}. Hash: {identity.hash.hex()}")
        else:
            identity = RNS.Identity()
            identity.to_file(identity_path)
            RNS.log(f"[INIT] Created new identity and saved to {identity_path}. Hash: {identity.hash.hex()}")
        return identity

    def initialize_reticulum(self):
        try:
            RNS.Reticulum()
            self.write_debug_log("[INIT] Reticulum initialized successfully.")
        except Exception as e:
            self.write_debug_log(f"[INIT] Error initializing Reticulum: {e}")
            raise e

    def initialize_client(self):
        try:
            identity_path = f"{RNS.Reticulum.storagepath}/retibbs_client_identity"
            self.write_debug_log(f"[DEBUG] Identity file path: {identity_path}")

            self.client_identity = self.load_or_create_identity(identity_path)
            self.write_debug_log(f"[DEBUG] Client identity hash: {self.client_identity.hash.hex()}")

            self.register_announce_handler()

        except Exception as e:
            self.write_log(f"[INIT] Failed to initialize client: {e}")
            RNS.log(f"[CLIENT] Error initializing client: {e}", RNS.LOG_ERROR)

    def register_announce_handler(self):
        try:
            self.announce_handler = AnnounceHandler(app=self, aspect_filter="retibbs.bbs")
            RNS.Transport.register_announce_handler(self.announce_handler)
            self.write_debug_log("[INIT] Announce handler registered.")
        except Exception as e:
            self.write_debug_log(f"[INIT] Failed to register announce handler: {e}")
            RNS.log(f"[CLIENT] Error registering announce handler: {e}", RNS.LOG_ERROR)

    async def on_mount(self):
        self.title = "- RetiBBS Client -"

        server_list = self.query_one("#server_list", DataTable)
        if not server_list.columns:
            server_list.add_columns("Server Name", "Destination Hash")

        address_book = self.query_one("#address_book", DataTable)
        if not address_book.columns:
            address_book.add_columns("Server Name", "Destination Hash")

        server_list.visible = True
        address_book.visible = True

        # Log deferred errors (if any)
        if hasattr(self, "_deferred_debug_log"):
            for message in self._deferred_debug_log:
                try:
                    debug_log = self.query_one("#debug_log", Log)
                    debug_log.write_line(message)
                except Exception:
                    continue  # Skip if still unavailable
            self._deferred_debug_log.clear()

        self.address_book = self.load_address_book()
        self.update_address_book()

        self.write_log("Initializing Reticulum...")
        try:
            self.initialize_reticulum()
            self.write_log("Reticulum initialized.")
        except Exception as e:
            self.write_log(f"Error initializing Reticulum: {e}")
            return

        self.write_log("Initializing client...")
        try:
            self.initialize_client()
            self.write_log("Client initialized.\n\nWelcome to RetiBBS!\n\n")
        except Exception as e:
            self.write_log(f"Error initializing client: {e}")
            return

        if self.server_hexhash:
            await self.connect_client()
        else:
            self.write_log("Server hexhash not provided. Please wait for an announce...")

    async def connect_client(self, destination_hash=None):
        server_hexhash = destination_hash or self.server_hexhash
        if not server_hexhash:
            self.write_log("[CONNECT] Failed: No server hexhash provided.")
            return

        try:
            try:
                server_addr = bytes.fromhex(server_hexhash)
            except ValueError:
                self.write_log(f"[CONNECT] Failed: Invalid server hexhash: {server_hexhash}.")
                return

            if not RNS.Transport.has_path(server_addr):
                self.write_log("[CONNECT] Path to server unknown, requesting path and waiting for announce...")
                RNS.Transport.request_path(server_addr)
                timeout_t0 = asyncio.get_event_loop().time()

                while not RNS.Transport.has_path(server_addr):
                    if asyncio.get_event_loop().time() - timeout_t0 > 15:
                        self.write_log("[CONNECT] Failed: Timed out waiting for path.")
                        return
                    await asyncio.sleep(0.1)

            server_identity = RNS.Identity.recall(server_addr)
            if not server_identity:
                self.write_log("[CONNECT] Failed: Could not recall server Identity.")
                return

            server_destination = RNS.Destination(
                server_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "retibbs",
                "bbs"
            )

            self.link = RNS.Link(server_destination)
            self.link.set_link_established_callback(self.on_link_established)
            self.link.set_link_closed_callback(self.on_link_closed)
            self.link.set_packet_callback(self.on_packet_received)

            # IMPORTANT: may need a refactoring to use a more restrictive resource strategy
            self.link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
            self.link.set_resource_started_callback(self.on_resource_started)
            self.link.set_resource_concluded_callback(self.on_resource_concluded)

            self.write_log("[CONNECT] Establishing link with server...")
            RNS.log("[CLIENT] Establishing link with server...")

            await self.wait_for_link()

            if self.link.status == RNS.Link.ACTIVE:
                self.write_log("[CONNECT] Link is ACTIVE. Now identifying to server...")
                self.link.identify(self.client_identity)
                self.write_log("[CONNECT] Successfully connected to the server.")
            else:
                self.write_log("[CONNECT] Failed: Link could not be established.")
                self.link = None

        except Exception as e:
            self.write_log(f"[CONNECT] Failed: Error connecting to server: {e}")
            RNS.log(f"[CLIENT] Error connecting to server: {e}", RNS.LOG_ERROR)

    async def wait_for_link(self):
        timeout_t0 = asyncio.get_event_loop().time()
        while self.link.status != RNS.Link.ACTIVE:
            if asyncio.get_event_loop().time() - timeout_t0 > 15:
                self.query_one("#main_log", Log).write_line("[CONNECT] Failed: Timed out waiting for link.")
                return
            await asyncio.sleep(0.1)
    
    def on_link_established(self, link):
        self.write_debug_log("[DEBUG] Link established!")
        self.write_debug_log(f"[DEBUG] Link status: {link.status}")
    
    def on_link_closed(self, link):
        self.write_log("Disconnected from the RetiBBS server.")

    def on_resource_started(self, resource):
        self.write_log(f"[RESOURCE] Started: {resource.id} (size={resource.size})")

    def on_resource_concluded(self, resource):
        if resource.data is not None:
            try:
                fileobj = resource.data
                fileobj.seek(0)
                data = fileobj.read()
                text = data.decode("utf-8", "ignore")
                self.write_log(f"[SERVER-RESOURCE]\n{text}")

                match = re.search(r"You have joined board '(.+)'", text)
                if match:
                    board_name = match.group(1)
                    self.write_log(f"You have joined board: {board_name}")
            except Exception as e:
                self.write_log(f"[RESOURCE] Error processing resource data: {e}")
        else:
            self.write_log("[SERVER-RESOURCE] Transfer concluded, but no data received!")

    # IMPORTANT: may need a refactoring, as this function is not working as
    # expected. May need to be removed if the server switches to using resources
    # only.
    def on_packet_received(self, packet):
        self.write_log("[SERVER-PACKET] Received packet.")
        try:
            self.write_log(f"[DEBUG] Raw packet: {packet}")
            self.write_log(f"[DEBUG] Packet data (bytes): {packet.data}")

            text = packet.data.decode("utf-8", "ignore")
            self.write_log(f"[SERVER-PACKET] Decoded text: {text}")

            match = re.search(r"You have joined board '(.+)'", text)
            if match:
                board_name = match.group(1)
                self.write_log(f"You have joined board: {board_name}")
                self.current_board = board_name
            elif "You are not in any board." in text:
                self.write_log("You are not in any board.")
                self.current_board = "None"
        except UnicodeDecodeError as e:
            self.write_log(f"[DEBUG] Error decoding packet data: {e}")
            self.write_log(f"[DEBUG] Non-UTF-8 packet data: {packet.data.hex()}")
        except Exception as e:
            self.write_log(f"[SERVER-PACKET] Error processing packet: {e}")

    async def on_input_submitted(self, message: Input.Submitted):
        command = message.value.strip()
        if command:
            self.write_log(f"Command: {command}")
            if self.link and self.link.status == RNS.Link.ACTIVE:
                try:
                    packet = RNS.Packet(self.link, command.encode("utf-8"))
                    packet.send()
                except Exception as e:
                    self.write_log(f"Error sending command: {e}")
            else:
                self.write_log("Not connected to a server.")
        message.input.value = ""

    def on_announce(self, destination_hash, announced_identity, app_data):
        # TOREMOVE: Debug log
        #self.write_debug_log("[ANNOUNCE] [Callback] Received announce packet.")

        dest_hash_hex = destination_hash.hex()
        display_name = RNS.prettyhexrep(destination_hash)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        if app_data:
            try:
                app_data_json = json.loads(app_data.decode("utf-8"))
                if "server_name" in app_data_json:
                    display_name = app_data_json["server_name"]
            except json.JSONDecodeError:
                pass

        self.servers[dest_hash_hex] = {
            "display_name": display_name,
            "hash": dest_hash_hex,
            "timestamp": timestamp,
        }

        self.call_later(self.update_server_list)
    
        self.write_debug_log(f"[ANNOUNCE] Discovered server: {display_name} ({dest_hash_hex})")

    def update_server_list(self):
        try:
            # Check if a modal is currently active
            if len(self.screen_stack) > 1 and isinstance(self.screen_stack[-1], ModalScreen):
                if not self.server_list_update_pending:
                    self.server_list_update_pending = True  # Set flag to avoid repeated deferrals
                    self.write_debug_log("[INFO] Modal is active, deferring server list update.")
                    self.call_later(self.update_server_list)  # Defer the update
                return

            # Proceed with updating the server list
            self.server_list_update_pending = False  # Reset the flag
            server_list = self.query_one("#server_list", DataTable)
            server_list.clear()
            for server in self.servers.values():
                server_list.add_row(server["display_name"], server["hash"])
            self.write_debug_log("[DEBUG] Server list updated successfully.")
        except Exception as e:
            self.server_list_update_pending = False  # Ensure the flag is reset on error
            self.write_debug_log(f"[ERROR] Error updating server list: {e}")
    
    def update_address_book(self):
        try:
            address_book = self.query_one("#address_book", DataTable)
            address_book.clear()
            for server in self.address_book.values():
                address_book.add_row(server["display_name"], server["hash"])
                self.write_debug_log(f"[DEBUG] Added to address book: {server['display_name']} - {server['hash']}")
            self.write_debug_log("[DEBUG] Address book updated successfully.")
        except Exception as e:
            self.write_debug_log(f"[DEBUG] Error updating address book: {e}")
    
    def toggle_address_book(self, destination_hash, currently_saved):
        if currently_saved:
            del self.address_book[destination_hash]
        else:
            server = self.servers[destination_hash]
            self.address_book[destination_hash] = server
        self.save_address_book()
        self.update_address_book()

    def action_refresh_servers(self):
        self.write_log("[ACTION] Refreshing server list...")
        server_list = self.query_one("#server_list", DataTable)
        server_list.clear()
        server_list.add_columns("Server Name", "Destination Hash")
        for server in self.servers.values():
            server_list.add_row(server["display_name"], server["hash"])
    
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            # Get the triggering table
            triggering_table = event.control
            table_id = triggering_table.id  # Retrieve the table's ID
            self.write_debug_log(f"[ACTION] Selected row in table: {table_id}, row key: {event.row_key}")

            if table_id == "server_list":
                # Handle server list selection
                row_data = triggering_table.get_row(event.row_key)
                if row_data:
                    server_name, destination_hash = row_data
                    server_info = self.servers.get(destination_hash)
                    if server_info:
                        self.push_screen(
                            ServerDetailScreen(
                                server_name=server_info["display_name"],
                                destination_hash=server_info["hash"],
                                timestamp=server_info["timestamp"],
                                on_connect=self.connect_client,
                                saved_in_address_book=destination_hash in self.address_book,
                            )
                        )
            elif table_id == "address_book":
                # Handle address book selection
                row_data = triggering_table.get_row(event.row_key)
                if row_data:
                    server_name, destination_hash = row_data
                    server_info = self.address_book.get(destination_hash)
                    if server_info:
                        self.push_screen(
                            ServerDetailScreen(
                                server_name=server_info["display_name"],
                                destination_hash=server_info["hash"],
                                timestamp=server_info["timestamp"],
                                on_connect=self.connect_client,
                                saved_in_address_book=True,
                            )
                        )
        except Exception as e:
            self.write_debug_log(f"[ERROR] Exception in row selection: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RetiBBS Client")
    parser.add_argument(
        "--server",
        type=str,
        required=False,
        help="Hexadecimal hash of the RetiBBS server",
    )
    args = parser.parse_args()

    app = RetiBBSClient(server_hexhash=args.server)
    app.run()
