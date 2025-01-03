import threading
import time
import json

import RNS

class AutomaticAnnouncer(threading.Thread):
    def __init__(self, server_destination, interval, server_name):
        super().__init__()
        self.server_destination = server_destination
        self.interval = interval
        self.server_name = server_name
        self.stop_event = threading.Event()
        self.daemon = True

    def run(self):
        while not self.stop_event.is_set():
            time.sleep(self.interval)
            announce_data = json.dumps({"server_name": self.server_name}).encode("utf-8")
            self.server_destination.announce(app_data=announce_data)
            RNS.log("[Announcer] Sent automatic announce", RNS.LOG_DEBUG)

    def stop(self):
        self.stop_event.set()