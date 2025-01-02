import time
import json

import RNS

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

        self.app.servers[dest_hash_raw] = announce_message

        if dest_hash_raw in self.app.address_book:
            self.app.address_book[dest_hash_raw]["timestamp"] = timestamp
            self.app.save_address_book()
            self.app.update_address_book()

        self.app.on_announce(destination_hash, announced_identity, app_data)