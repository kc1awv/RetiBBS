#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import re
import threading
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, TabbedContent, TabPane, Input, Log, RichLog, DataTable, Static, Button, Label

from rich.text import Text

from announce_handler import AnnounceHandler
from modals import ServerDetailScreen, HelpScreen

import RNS

PING_INTERVAL = 10
PING_TIMEOUT = 15
ADDRESS_BOOK_FILE = "address_book.json"

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
        self.connection_status = "Not Connected"
        self.current_server_name = None
        self.heartbeat_running = False
        self.monitor_running = False
        self.last_ping_time = None
        self.last_pong_time = None

    def compose(self) -> ComposeResult:
        yield Header()
        
        main_screen = TabPane(title="Main", id="main")
        main_screen.compose_add_child(
            RichLog(markup=True, wrap=True, id="main_log")
        )

        log_screen = TabPane(title="Log", id="debug")
        log_screen.compose_add_child(
            Log(id="debug_log")
        )

        screens = TabbedContent(id="screens", classes="screens")
        screens.compose_add_child(main_screen)
        screens.compose_add_child(log_screen)
        screens.default_tab = "Main"

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
                screens,
                Static(self.connection_status, id="connection_status"),
                Static("", id="connection_latency", classes="hidden"),
                Input(placeholder="Enter command...", id="command_input"),
                id="left_panel"
            ),
            Vertical(
                tabs,
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
                    #DEBUG: self._deferred_debug_log.append(f"[DEBUG] Address book loaded: {address_book}")
                    return address_book
            except Exception as e:
                self._deferred_debug_log.append(f"[ERROR] Error loading address book: {e}")
        return {}
    
    def save_address_book(self):
        with open(ADDRESS_BOOK_FILE, "w") as file:
            json.dump(self.address_book, file, indent=4)

    def write_debug_log(self, message):
        try:
            debug_log = self.query_one("#debug_log", Log)
            debug_log.write_line(message)
        except Exception:
            if not hasattr(self, "_deferred_debug_log"):
                self._deferred_debug_log = []
            self._deferred_debug_log.append(message)
    
    def write_log(self, message):
        log = self.query_one(RichLog)
        log.write(message)

    def load_or_create_identity(self, identity_path=None):
        if not identity_path:
            identity_path = f"{RNS.Reticulum.storagepath}/retibbs_client_identity"

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
            if hasattr(self, "reticulum_config_path") and self.reticulum_config_path:
                RNS.Reticulum.initialize(self.reticulum_config_path)
                self.write_debug_log(f"[INIT] Reticulum initialized with config: {self.reticulum_config_path}.")
            else:
                RNS.Reticulum()
                self.write_debug_log("[INIT] Reticulum initialized with default config.")
        except Exception as e:
            self.write_debug_log(f"[INIT] Error initializing Reticulum: {e}")
            raise e

    def initialize_client(self):
        try:
            self.write_debug_log(f"[INIT] Using identity file: {self.identity_file_path or 'default'}")
            self.client_identity = self.load_or_create_identity(self.identity_file_path)
            self.write_debug_log(f"[INIT] Client identity hash: {self.client_identity.hash.hex()}")
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

        if hasattr(self, "_deferred_debug_log"):
            for message in self._deferred_debug_log:
                try:
                    debug_log = self.query_one("#debug_log", Log)
                    debug_log.write_line(message)
                except Exception:
                    continue
            self._deferred_debug_log.clear()

        self.address_book = self.load_address_book()
        self.update_address_book()

        self.update_connection_status()

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
            self.write_log("Server hexhash not provided from the command line.\nSelect a server from your address book or please wait for an announce...")
    
    async def action_quit(self) -> None:
        try:
            if self.link and self.link.status == RNS.Link.ACTIVE:
                self.write_debug_log("[QUIT] Closing active link to the server.")
                self.link.teardown()
                await asyncio.sleep(1)
                self.on_link_closed(self.link)
            else:
                self.write_debug_log("[QUIT] No active link to close.")
        except Exception as e:
            self.write_debug_log(f"[QUIT] Error during cleanup: {e}")
        finally:
            self.exit()

    def action_show_help(self):
        self.push_screen(HelpScreen())

    def update_connection_status(self):
        if self.link and self.link.status == RNS.Link.ACTIVE:
            indicator = Text("\u2713 ", style="bold green")
            status = f"Connected to {self.current_server_name or 'Unknown Server'}"
            if hasattr(self, "current_area") and self.current_area:
                status += f" | {self.current_area}"
                if hasattr(self, "current_board") and self.current_board:
                    status += f" | Board: {self.current_board}"
        else:
            indicator = Text("\u2715  ", style="bold red")
            status = "Not Connected"
            latency_widget = self.query_one("#connection_latency", Static)
            latency_widget.visible = False
        status_widget = self.query_one("#connection_status", Static)
        status_widget.update(indicator + Text(status))

    async def connect_client(self, destination_hash=None):
        self.last_ping_time = None
        self.last_pong_time = None

        server_hexhash = destination_hash or self.server_hexhash
        if not server_hexhash:
            self.write_log("[CONNECT] Failed: No server hexhash provided.")
            self.update_connection_status()
            return

        try:
            try:
                server_info = self.address_book.get(server_hexhash) or self.servers.get(server_hexhash)
                self.current_server_name = server_info.get("display_name", "Unknown Server") if server_info else "Unknown Server"
                self.update_connection_status()
                server_addr = bytes.fromhex(server_hexhash)
            except ValueError:
                self.write_log(f"[CONNECT] Failed: Invalid server hexhash: {server_hexhash}.")
                return

            if not RNS.Transport.has_path(server_addr):
                self.write_log("[CONNECT] Path to server unknown, requesting path...")
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
                self.update_connection_status()
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
            await self.wait_for_link()

            if self.link.status == RNS.Link.ACTIVE:
                self.write_log("[CONNECT] Link is ACTIVE. Now identifying to server...")
                self.link.identify(self.client_identity)
                self.write_log("[CONNECT] Successfully connected to the server.\n\n")
                self.update_connection_status()
                try:
                    self.heartbeat_running = True
                    self.monitor_running = True
                    self.start_heartbeat()
                    self.start_connection_monitor()
                    self.write_debug_log("[CONNECT] Connection monitoring started.")
                except Exception as e:
                    self.write_log(f"[CONNECT] Error starting connection monitoring: {e}")
            else:
                self.write_log("[CONNECT] Failed: Link could not be established.\n\n")
                self.link = None
                self.current_server_name = None
                self.heartbeat_running = False
                self.monitor_running = False
                self.update_connection_status()

        except Exception as e:
            self.write_log(f"[CONNECT] Failed: Error connecting to server: {e}")
            self.current_server_name = None
            self.update_connection_status()

    async def wait_for_link(self):
        timeout_t0 = asyncio.get_event_loop().time()
        while self.link.status != RNS.Link.ACTIVE:
            if asyncio.get_event_loop().time() - timeout_t0 > 15:
                self.query_one("#main_log", Log).write_line("[CONNECT] Failed: Timed out waiting for link.")
                return
            await asyncio.sleep(0.1)
    
    def on_link_established(self, link):
        #DEBUG: self.write_debug_log("[DEBUG] Link established!")
        #DEBUG: self.write_debug_log(f"[DEBUG] Link status: {link.status}")
        main_screen = self.query_one("#main_log", RichLog)
        main_screen.clear()
        latency_widget = self.query_one("#connection_latency", Static)
        latency_widget.update(f"Connection Latency (RTT): [CALCULATING]")
        latency_widget.visible = True
    
    def start_heartbeat(self):
        def heartbeat():
            try:
                #DEBUG: self.write_debug_log("[DEBUG] Starting heartbeat thread...")
                while self.heartbeat_running:
                    if self.link and self.link.status == RNS.Link.ACTIVE:
                        self.send_ping()
                    time.sleep(PING_INTERVAL)
            except Exception as e:
                self.write_debug_log(f"[ERROR] Error in heartbeat thread: {e}")
        
        self.write_debug_log("[INIT] Heartbeat thread started.")
        threading.Thread(target=heartbeat, daemon=True).start()
    
    def start_connection_monitor(self):
        def monitor():
            try:
                #DEBUG: self.write_debug_log("[DEBUG] Starting connection monitor thread...")
                while self.monitor_running:
                    self.check_pong_timeout()
                    time.sleep(1)
            except Exception as e:
                self.write_debug_log(f"[ERROR] Error in connection monitor thread: {e}")
        self.write_debug_log("[INIT] Connection monitor thread started.")
        threading.Thread(target=monitor, daemon=True).start()
    
    def send_ping(self):
        try:
            self.last_ping_time = time.time()
            packet = RNS.Packet(self.link, b"PING")
            packet.send()
            #DEBUG: self.write_debug_log("[DEBUG] Sent PING to server.")
        except Exception as e:
            self.write_log(f"[Client] Error sending PING: {e}")
    
    def check_pong_timeout(self):
        if self.last_pong_time:
            time_since_last_pong = time.time() - self.last_pong_time
            #DEBUG: self.write_debug_log(f"[DEBUG] Time since last PONG: {time_since_last_pong:.3f} seconds")
            if time_since_last_pong > PING_TIMEOUT:
                self.write_log("[Client] No PONG received within timeout.")
                self.teardown_connection()
    
    def teardown_connection(self):
        self.heartbeat_running = False
        self.monitor_running = False
        self.last_ping_time = None
        self.last_pong_time = None
        latency_widget = self.query_one("#connection_latency", Static)
        latency_widget.visible = False
        if self.link:
            self.link.teardown()
            self.link = None
        self.current_server_name = None
        self.current_board = None
        self.update_connection_status()
        self.write_log("Connection lost.")

    def on_link_closed(self, link):
        self.heartbeat_running = False
        self.monitor_running = False
        self.last_ping_time = None
        self.last_pong_time = None
        latency_widget = self.query_one("#connection_latency", Static)
        latency_widget.visible = False
        self.link = None
        self.current_server_name = None
        self.current_board = None
        self.update_connection_status()
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
                self.write_log(f"{text}")
            except Exception as e:
                self.write_log(f"[RESOURCE] Error processing resource data: {e}")
        else:
            self.write_log("Transfer concluded, but no data received!")

    def on_packet_received(self, message_bytes, packet):
        if message_bytes == b"PONG":
            self.last_pong_time = time.time()
            round_trip_time = self.last_pong_time - self.last_ping_time
            latency_widget = self.query_one("#connection_latency", Static)
            latency_widget.update(f"Connection Latency (RTT): {round_trip_time:.3f} seconds")
            return
        elif message_bytes.startswith(b"CTRL CLS"):
            main_screen = self.query_one("#main_log", RichLog)
            main_screen.clear()
        elif message_bytes.startswith(b"CTRL AREA"):
            try:
                decoded_message = message_bytes.decode("utf-8")
                area_name = decoded_message[len("CTRL AREA "):].strip()
                self.current_area = area_name
                self.write_debug_log(f"[INFO] Area update: {area_name}")
                if self.current_area != "Message Boards":
                    self.current_board = None
                self.update_connection_status()
            except Exception as e:
                self.write_log(f"[SERVER-PACKET] Error processing area update: {e}")
        elif message_bytes.startswith(b"CTRL BOARD"):
            try:
                decoded_message = message_bytes.decode("utf-8")
                board_name = decoded_message[len("CTRL BOARD "):].strip()
                self.current_board = board_name
                self.write_debug_log(f"[INFO] Board update: {board_name}")
                self.update_connection_status()
            except Exception as e:
                self.write_log(f"[SERVER-PACKET] Error processing board update: {e}")
        else:
            try:
                text = message_bytes.decode("utf-8", "ignore")
                self.write_log(f"{text}")

                match = re.search(r"You have joined board '(.+)'", text)
                if match:
                    board_name = match.group(1)
                    self.current_board = board_name
                elif "You are not in any board." in text:
                    self.current_board = "None"
                self.update_connection_status()
            except UnicodeDecodeError as e:
                self.write_log(f"[ERROR] Error decoding packet data: {e}")
                self.write_log(f"[ERROR] Non-UTF-8 packet data: {message_bytes.data.hex()}")
            except Exception as e:
                self.write_log(f"[SERVER-PACKET] Error processing packet: {e}")

    async def on_input_submitted(self, message: Input.Submitted):
        command = message.value.strip()
        if command:
            self.write_log(f"\nCommand: {command}")
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
            if len(self.screen_stack) > 1 and isinstance(self.screen_stack[-1], ModalScreen):
                if not self.server_list_update_pending:
                    self.server_list_update_pending = True
                    self.write_debug_log("[INFO] Modal is active, deferring server list update.")
                    self.call_later(self.update_server_list)
                return

            self.server_list_update_pending = False
            server_list = self.query_one("#server_list", DataTable)
            server_list.clear()
            for server in self.servers.values():
                server_list.add_row(server["display_name"], server["hash"])
            #DEBUG: self.write_debug_log("[DEBUG] Server list updated successfully.")
        except Exception as e:
            self.server_list_update_pending = False
            self.write_debug_log(f"[ERROR] Error updating server list: {e}")
    
    def update_address_book(self):
        try:
            address_book = self.query_one("#address_book", DataTable)
            address_book.clear()
            for server in self.address_book.values():
                address_book.add_row(server["display_name"], server["hash"])
                #DEBUG: self.write_debug_log(f"[DEBUG] Added to address book: {server['display_name']} - {server['hash']}")
            #DEBUG: self.write_debug_log("[DEBUG] Address book updated successfully.")
        except Exception as e:
            self.write_debug_log(f"[ERROR] Error updating address book: {e}")
    
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
            triggering_table = event.control
            table_id = triggering_table.id
            #DEBUG: self.write_debug_log(f"[ACTION] Selected row in table: {table_id}, row key: {event.row_key}")

            if table_id == "server_list":
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
        "--reticulum-config",
        type=str,
        required=False,
        help="Path to an alternative Reticulum configuration directory",
    )
    parser.add_argument(
        "--identity-file",
        type=str,
        required=False,
        help="Path to an alternative client identity file",
    )
    parser.add_argument(
        "--server",
        type=str,
        required=False,
        help="Hexadecimal hash of the RetiBBS server",
    )
    args = parser.parse_args()

    app = RetiBBSClient(server_hexhash=args.server)
    app.reticulum_config_path = args.reticulum_config
    app.identity_file_path = args.identity_file
    app.run()
