import json

from web.web_server import app
from boards_manager import BoardsManager

try:
    with open("server_config.json", "r") as f:
        config = json.load(f)
    app.config["server_name"] = config.get("server_name", "RetiBBS")
except FileNotFoundError:
    app.config["server_name"] = "RetiBBS"

boards_manager = BoardsManager(users_manager=None, reply_manager=None, lxmf_handler=None, theme_manager=None)
app.config["boards_manager"] = boards_manager

retibbs_web = app