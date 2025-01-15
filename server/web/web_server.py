from flask import render_template, jsonify, request
from . import app
from datetime import datetime

class WebServer:
    def __init__(self, boards_manager, server_name):
        self.boards_manager = boards_manager
        self.server_name = server_name

    def start(self, host="127.0.0.1", port=5000, debug=False):
        app.config["boards_manager"] = self.boards_manager
        app.config["server_name"] = self.server_name
        app.run(host=host, port=port)

@app.context_processor
def inject_server_name():
    default_server_name = "RetiBBS"
    server_name = app.config.get("server_name", default_server_name)
    year = datetime.now().year
    return {
        "server_name": server_name,
        "is_default_name": server_name == default_server_name,
        "year": year
    }

@app.template_filter("format_timestamp")
def format_timestamp_filter(timestamp):
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Invalid timestamp"

@app.route("/")
def index():
    boards_manager = app.config.get("boards_manager")
    boards = boards_manager.list_boards()

    boards = []
    for board_name in boards_manager.list_boards():
        messages, total_messages = boards_manager.list_messages(board_name, page=1, page_size=1)
        if messages:
            last_message = messages[0]
            boards.append({
                "name": board_name,
                "last_message_time": last_message["timestamp"],
                "last_message_author": last_message["author"],
            })
        else:
            boards.append({
                "name": board_name,
                "last_message_time": None,
                "last_message_author": None,
            })

    return render_template("index.html", boards=boards)

@app.route("/board/<board_name>")
def view_board(board_name):
    boards_manager = app.config.get("boards_manager")
    page = int(request.args.get("page", 1))
    page_size = 10
    messages, total_messages = boards_manager.list_messages(board_name, page, page_size)
    total_pages = (total_messages + page_size - 1) // page_size
    return render_template(
        "board.html",
        board_name=board_name,
        messages=messages,
        page=page,
        total_pages=total_pages
    )

@app.route("/api/boards")
def api_boards():
    boards = app.config.get("boards", {})
    return jsonify(list(boards.keys()))

@app.route("/api/board/<board_name>")
def api_board(board_name):
    boards_manager = app.config.get("boards_manager")
    page = int(request.args.get("page", 1))
    page_size = 10
    messages, _ = boards_manager.list_messages(board_name, page, page_size)
    return jsonify(messages)

@app.route("/api/message/<int:message_id>")
def api_message(message_id):
    boards_manager = app.config.get("boards_manager")
    message = boards_manager.get_message_by_id(message_id)
    if message:
        replies = boards_manager.list_replies(message_id)
        return render_template("message_modal.html", message=message, replies=replies)
    return "<p>Message not found</p>", 404
