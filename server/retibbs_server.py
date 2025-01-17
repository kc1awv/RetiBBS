#!/usr/bin/env python3
import argparse
import os
import json
import sys
import threading

import RNS

from automatic_announcer import AutomaticAnnouncer
from boards_manager import BoardsManager
from identity_manager import IdentityManager
from lxmf_handler import LXMFHandler
from main_menu import MainMenuHandler
from reply_handler import ReplyHandler
from theme_manager import ThemeManager
from users_manager import UsersManager
from web.web_server import WebServer

class RetiBBSServer:
    def __init__(
            self,
            configpath,
            identity_file,
            server_name,
            announce_interval,
            enable_web_server,
            use_wsgi
        ):
        self.configpath = configpath
        self.identity_file = identity_file
        self.server_name = server_name
        self.announce_interval = announce_interval
        self.enable_web_server = enable_web_server
        self.use_wsgi = use_wsgi
        self.users_mgr = UsersManager()
        self.reply_handler = ReplyHandler()
        self.theme_mgr = ThemeManager()
        self.theme_mgr.load_config()
        self.theme_mgr.load_theme()
        self.main_menu_handler = MainMenuHandler(self.users_mgr, self.reply_handler, None, self.theme_mgr)
        self.boards_mgr = BoardsManager(self.users_mgr, self.reply_handler, None, self.theme_mgr)
        self.web_server = None
        self.latest_client_link = None
        self.server_identity = None
        self.server_destination = None
        self.announcer = None
        
        if enable_web_server and not use_wsgi:
            self.web_server = WebServer(self.boards_mgr, self.server_name)

        self.server_setup()

    def server_setup(self):
        RNS.Reticulum(self.configpath)
        identity_manager = IdentityManager(self.identity_file)
        self.server_identity = identity_manager.load_or_create_identity()

        self.server_destination = RNS.Destination(
            self.server_identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "retibbs",
            "bbs"
        )
        self.server_destination.set_link_established_callback(self.client_connected)

        self.lxmf_handler = LXMFHandler(
            storage_path="./lxmf_storage",
            identity=self.server_identity,
            display_name=self.server_name
        )
        self.lxmf_handler.set_delivery_callback(self.lxmf_delivery_callback)
        self.main_menu_handler.lxmf_handler = self.lxmf_handler
        self.boards_mgr.lxmf_handler = self.lxmf_handler

        RNS.log(f"[Server] BBS Server running. Identity hash: {RNS.prettyhexrep(self.server_destination.hash)}", RNS.LOG_INFO)

        if self.announce_interval > 0:
            self.announcer = AutomaticAnnouncer(
                self.server_destination,
                self.announce_interval,
                self.server_name
            )
            self.announcer.start()
            RNS.log(f"[Server] Automatic announce set to every {announce_interval} seconds.", RNS.LOG_INFO)

    def start_web_server(self):
        if self.use_wsgi:
            RNS.log("[Server] Using WSGI mode, skipping web server start.", RNS.LOG_INFO)
        elif self.web_server:
            RNS.log("[Server] Starting Flask development web server...", RNS.LOG_INFO)
            web_thread = threading.Thread(target=self.web_server.start, daemon=True)
            web_thread.start()

    def run(self):
        if self.enable_web_server:
            self.start_web_server()
        while True:
            try:
                RNS.log("[Server] Waiting for incoming connections... Press Enter to send an ANNOUNCE.", RNS.LOG_INFO)
                input()
                RNS.log("[Server] Sending manual announce...", RNS.LOG_INFO)
                self.send_announce()
            except KeyboardInterrupt:
                RNS.log("[Server] Keyboard interrupt received, shutting down...", RNS.LOG_INFO)
                self.shutdown()
                break

    def send_announce(self):
        announce_data = json.dumps({"server_name": self.server_name}).encode("utf-8")
        self.server_destination.announce(app_data=announce_data)
        RNS.log("[Server] Sent announce from " + RNS.prettyhexrep(self.server_destination.hash), RNS.LOG_DEBUG)

    def shutdown(self):
        RNS.log("[Server] Shutdown initiated.", RNS.LOG_INFO)
        if self.announcer:
            try:
                RNS.log("[Server] Stopping automatic announcer...", RNS.LOG_INFO)
                self.announcer.stop()
                self.announcer.join()
                RNS.log("[Server] Automatic announcer stopped.", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[Server] Error stopping automatic announcer: {e}", RNS.LOG_ERROR)
        RNS.log("[Server] Shutting down Reticulum...", RNS.LOG_INFO)
        try:
            RNS.Reticulum.exit_handler()
        except Exception as e:
            RNS.log(f"[Server] Error during Reticulum shutdown: {e}", RNS.LOG_ERROR)
        RNS.log("[Server] Logs flushed, exiting...", RNS.LOG_INFO)
        sys.stdout.flush()
        sys.stderr.flush()

    def client_connected(self, link):
        RNS.log("[Server] Client link established!", RNS.LOG_DEBUG)

        link.set_link_closed_callback(self.client_disconnected)
        link.set_packet_callback(self.server_packet_received)
        link.set_remote_identified_callback(self.remote_identified)
        self.latest_client_link = link

        # FUTURE: automatically accept inbound resources from the client:
        # link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
        # link.set_resource_started_callback(resource_started_callback)
        # link.set_resource_concluded_callback(resource_concluded_callback)

    def client_disconnected(self, link):
        RNS.log("[Server] Client disconnected.", RNS.LOG_DEBUG)
        remote_identity = link.get_remote_identity()
        self.users_mgr.remove_user_session(remote_identity.hash.hex())
        RNS.log(f"[Server] Removed user session for {RNS.prettyhexrep(bytes.fromhex(remote_identity.hash.hex()))}", RNS.LOG_DEBUG)

    def remote_identified(self, link, identity):
        identity_hash_hex = identity.hash.hex()

        RNS.log(f"[Server] Remote identified as {RNS.prettyhexrep(bytes.fromhex(identity_hash_hex))}", RNS.LOG_DEBUG)

        user = self.users_mgr.get_user(identity_hash_hex)

        if user is None:
            self.users_mgr.add_user(identity_hash_hex, name=None, is_admin=False)
            RNS.log(f"[Server] Added new user {RNS.prettyhexrep(bytes.fromhex(identity_hash_hex))} to database.", RNS.LOG_DEBUG)

        self.users_mgr.set_user_area(identity_hash_hex, "main_menu")
        self.users_mgr.set_user_board(identity_hash_hex, None)

        welcome_message = self.theme_mgr.apply_theme(self)

        self.reply_handler.send_clear_screen(link)
        self.reply_handler.send_area_update(link, "Main Menu")
        self.reply_handler.send_resource_reply(link, welcome_message)

        main_menu_message = self.theme_mgr.theme_files.get("main_menu.txt", "Main Menu: [?] Help [h] Hello [n] Name [b] Boards Area [lo] Log Out")
        self.reply_handler.send_resource_reply(link, main_menu_message)
    
    def lxmf_delivery_callback(self, message):
        RNS.log(f"[LXMF] Message delivered: {message.title if message.title else 'No Title'}", RNS.LOG_INFO)

    def server_packet_received(self, message_bytes, packet):
        remote_identity = packet.link.get_remote_identity()
        if not remote_identity:
            RNS.log("[Server] Received data from an unidentified peer.", RNS.LOG_WARNING)
            return

        identity_hash_hex = remote_identity.hash.hex()
        user = self.users_mgr.get_user(identity_hash_hex)

        if not user:
            RNS.log("[Server] Received data from an unknown user.", RNS.LOG_WARNING)
            return

        user_area = self.users_mgr.get_user_area(identity_hash_hex)
        user_display_name = user.get("name", RNS.prettyhexrep(bytes.fromhex(identity_hash_hex)))

        if message_bytes == b"PING":
            try:
                reply_packet = RNS.Packet(packet.link, b"PONG")
                reply_packet.send()
                RNS.log(f"[Server] Received PING from {identity_hash_hex}, sent PONG", RNS.LOG_DEBUG)
            except Exception as e:
                RNS.log(f"[Server] Error sending PONG: {e}", RNS.LOG_ERROR)
            return
        else:
            try:
                msg_str = message_bytes.decode("utf-8").strip()
            except:
                RNS.log("[Server] Error decoding message!", RNS.LOG_ERROR)
                return

            RNS.log(f"[Server] Received: {msg_str} from {user_display_name}", RNS.LOG_DEBUG)
            RNS.log(f"[Server] User area: {user_area}", RNS.LOG_DEBUG)

            if user_area == "main_menu":
                self.main_menu_handler.handle_main_menu_commands(msg_str, packet, identity_hash_hex)
            elif user_area == "boards":
                self.boards_mgr.handle_board_commands(msg_str, packet, identity_hash_hex)
            else:
                self.reply_handler.send_link_reply(packet.link, "ERROR: Unknown area.")

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="RetiBBS Server")
        parser.add_argument(
            "--reticulum-config",
            action="store",
            default=None,
            help="Path to alternative Reticulum config directory",
            type=str
        )
        parser.add_argument(
            "--identity-file",
            action="store",
            default="server_identity.pem",
            help="Path to store or load the server identity (private key)",
            type=str
        )
        parser.add_argument(
            "--config-file",
            action="store",
            default="server_config.json",
            help="Path to server configuration file (JSON)",
            type=str
        )
        args = parser.parse_args()

        if os.path.isfile(args.config_file):
            try:
                with open(args.config_file, "r", encoding="utf-8") as f:
                    server_config = json.load(f)
                server_name = server_config.get("server_name", "RetiBBS Server")
                announce_interval = server_config.get("announce_interval", 0)
                enable_web_server = server_config.get("enable_web_server", False)
                use_wsgi = server_config.get("use_wsgi", False)
                RNS.log(f"[Server] Loaded server name: '{server_name}' from {args.config_file}", RNS.LOG_INFO)
                RNS.log(f"[Server] Loaded announce interval: {announce_interval} seconds from {args.config_file}", RNS.LOG_INFO)
                RNS.log(f"[Server] Loaded web server enabled: {enable_web_server} from {args.config_file}", RNS.LOG_INFO)
                RNS.log(f"[Server] Loaded WSGI mode enabled: {use_wsgi} from {args.config_file}", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[Server] Could not load server configuration: {e}", RNS.LOG_ERROR)
                server_name = "RetiBBS Server"
                announce_interval = 0
                enable_web_server = False
                use_wsgi = False
        else:
            RNS.log(f"[Server] Configuration file {args.config_file} not found. Using defaults.", RNS.LOG_WARNING)
            server_name = "RetiBBS Server"
            announce_interval = 0
            enable_web_server = False
            use_wsgi = False

        server = RetiBBSServer(
            args.reticulum_config,
            args.identity_file,
            server_name,
            announce_interval,
            enable_web_server,
            use_wsgi
        )
        server.run()

    except Exception as e:
        RNS.log(f"[Server] Unexpected Error: {e}", RNS.LOG_ERROR)
        sys.exit(1)