import os
import RNS

class IdentityManager:
    def __init__(self, identity_path):
        self.identity_path = identity_path

    def load_or_create_identity(self):
        """
        Loads (or creates) the server's own private key Identity.
        """
        if os.path.isfile(self.identity_path):
            server_identity = RNS.Identity.from_file(self.identity_path)
            RNS.log(f"[Identity] Loaded server Identity from {self.identity_path}", RNS.LOG_INFO)
        else:
            server_identity = RNS.Identity()
            server_identity.to_file(self.identity_path)
            RNS.log(f"[Identity] Created new server Identity and saved to {self.identity_path}", RNS.LOG_INFO)
        return server_identity