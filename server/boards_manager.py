import time
import sqlite3
import threading

from datetime import datetime, timezone

import RNS

class BoardsManager:
    def __init__(self, users_manager, reply_manager, db_path='boards.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.users_mgr = users_manager
        self.reply_handler = reply_manager
        self._initialize_database()

    def _initialize_database(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()

                # Enable foreign key constraints
                cursor.execute("PRAGMA foreign_keys = ON;")

                # Create boards table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS boards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL
                    );
                """)

                # Create messages table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        board_id INTEGER NOT NULL,
                        timestamp REAL NOT NULL,
                        author TEXT NOT NULL,
                        content TEXT NOT NULL,
                        FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
                    );
                """)

                # Optional: Create users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hash_hex TEXT UNIQUE NOT NULL,
                        name TEXT
                    );
                """)

                conn.commit()
                RNS.log(f"[BoardsManager] Database initialized at {self.db_path}", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[BoardsManager] Error initializing database: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()
    
    def handle_board_commands(self, command, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)

        tokens = command.split(None, 1)
        if not tokens:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND\n")
            return
        
        cmd = tokens[0].lower()
        remainder = tokens[1] if len(tokens) > 1 else ""

        if cmd in ["?", "help"]:
            reply = (
                "You are in the message boards area.\n\n"
                "Available Commands:\n"
                "  ?  | help                     - Show this help text\n"
                "  b  | back                     - Return to main menu\n"
                "  lb | listboards               - List all boards\n"
                "  cb | changeboard <boardname>  - Switch to a board (so you can post/list by default)\n"
                "  p  | post <text>              - Post a message to your current board\n"
                "  lm | listmessages [boardname] - List messages in 'boardname' or your current board\n"
            )
            if user.get("is_admin", False):
                reply += (
                    "\n\nAdmin Commands:\n"
                    "  nb | newboard <name>          - Create a new board\n"
                    "  db | deleteboard <boardname>  - Delete a board\n"
            )
            self.reply_handler.send_resource_reply(packet.link, reply)
        elif cmd in ["b", "back"]:
            self.users_mgr.update_user(user_hash, current_area="main_menu")
            self.reply_handler.send_link_reply(packet.link, "Returning to main menu.")
        elif cmd in ["lb", "listboards"]:
            self.handle_list_boards(packet)
        elif cmd in ["cb", "changeboard"]:
            board_name = remainder.strip()
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "Usage: CHANGEBOARD <board_name>")
                return
            self.handle_join_board(packet, user_hash, board_name)
        elif cmd in ["p", "post"]:
            post_text = remainder.strip()
            if not post_text:
                self.reply_handler.send_link_reply(packet.link, "Usage: POST <text>")
                return
            user_info = self.users_mgr.get_user(user_hash)
            board_name = user_info.get("current_board")
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "You are not in a board area.")
                return
            self.post_message(board_name, user_info["name"], remainder)
            reply = f"Posted to board '{board_name}': {post_text}"
            self.reply_handler.send_link_reply(packet.link, reply)
        elif cmd in ["lm", "listmessages"]:
            board_name = remainder.strip()
            if board_name:
                self.handle_list_messages(packet, board_name)
            else:
                cur_board = user.get("current_board")
                if not cur_board:
                    self.reply_handler.send_link_reply(packet.link, "You are not in any board. Use BOARD <board> first.")
                else:
                    self.handle_list_messages(packet, cur_board)
        elif cmd in ["nb", "newboard"]:
            user_info = self.users_mgr.get_user(user_hash)
            if not user_info.get("is_admin", False):
                self.reply_handler.send_link_reply(packet.link, "ERROR: Only admins can create boards.")
                return
            board_name = remainder.strip()
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "Usage: NEWBOARD <board_name>")
                return
            if not self.is_valid_board_name(board_name):
                self.reply_handler.send_link_reply(packet.link, "ERROR: Invalid board name. Must be alphanumeric and 3-20 characters long.")
                return
            self.create_board(board_name)
            self.reply_handler.send_link_reply(packet.link, f"Board '{board_name}' is ready.")
        elif cmd in ["db", "deleteboard"]:
            user_info = self.users_mgr.get_user(user_hash)
            if not user_info.get("is_admin", False):
                self.reply_handler.send_link_reply(packet.link, "ERROR: Only admins can delete boards.")
                return
            board_name = remainder.strip()
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "Usage: DELETEBOARD <board_name>")
                return
            if not self.delete_board(board_name):
                self.reply_handler.send_link_reply(packet.link, f"Board '{board_name}' does not exist.")
            else:
                self.reply_handler.send_link_reply(packet.link, f"Board '{board_name}' has been deleted.")
        else:
            self.reply_handler.send_link_reply(packet.link, f"Unknown command: {cmd} in board area.")

    def handle_list_boards(self, packet):
        names = self.list_boards()
        if not names:
            reply = "No boards exist."
        else:
            reply = "All Boards:\n" + "\n".join(names) + "\n"
        self.reply_handler.send_resource_reply(packet.link, reply)

    def handle_join_board(self, packet, user_hash, board_name):
        user_info = self.users_mgr.get_user(user_hash)
        current = user_info.get("current_board")

        if current == board_name:
            reply = f"You are already in board '{board_name}'"
        else:
            self.users_mgr.update_user(user_hash, current_board=board_name)
            reply = f"You have joined board '{board_name}'"

        self.reply_handler.send_link_reply(packet.link, reply)

    def handle_list_messages(self, packet, board_name):
        posts = self.list_messages(board_name)
        if not posts:
            reply = f"No messages on board '{board_name}'"
        else:
            lines = []
            for m in posts:
                t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["timestamp"]))
                lines.append(f"[{t_str} {m['author']}] {m['content']}")
            reply = "\n".join(lines) + "\n"
        self.reply_handler.send_resource_reply(packet.link, reply)

    def is_valid_board_name(self, board_name):
        return board_name.isalnum() and 3 <= len(board_name) <= 20

    def create_board(self, board_name):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO boards (name) VALUES (?);", (board_name,))
                conn.commit()
                RNS.log(f"[BoardsManager] Created new board '{board_name}'", RNS.LOG_DEBUG)
            except sqlite3.IntegrityError:
                RNS.log(f"[BoardsManager] Board '{board_name}' already exists", RNS.LOG_ERROR)
            except Exception as e:
                RNS.log(f"[BoardsManager] Error creating board '{board_name}': {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def post_message(self, board_name, author, content):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()

                cursor.execute("SELECT id FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                if not result:
                    cursor.execute("INSERT INTO boards (name) VALUES (?);", (board_name,))
                    board_id = cursor.lastrowid
                    RNS.log(f"[BoardsManager] Auto-created board '{board_name}'")
                else:
                    board_id = result[0]

                timestamp = datetime.now(timezone.utc).timestamp()
                cursor.execute("""
                    INSERT INTO messages (board_id, timestamp, author, content)
                    VALUES (?, ?, ?, ?);
                """, (board_id, timestamp, author, content))
                conn.commit()
                RNS.log(f"[BoardsManager] New message posted to '{board_name}' by '{author}' at {timestamp} UTC", RNS.LOG_DEBUG)
            except Exception as e:
                RNS.log(f"[BoardsManager] Error posting message to '{board_name}': {e}", RNS.LOG_ERROR)
            finally:
                conn.close()
    
    def list_boards(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM boards ORDER BY name ASC;")
                rows = cursor.fetchall()
                board_names = [row[0] for row in rows]
                return board_names
            except Exception as e:
                RNS.log(f"[BoardsManager] Error listing boards: {e}", RNS.LOG_ERROR)
                return []
            finally:
                conn.close()

    def list_messages(self, board_name):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                if not result:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.", RNS.LOG_ERROR)
                    return []

                board_id = result[0]
                cursor.execute("""
                    SELECT timestamp, author, content FROM messages
                    WHERE board_id = ?
                    ORDER BY timestamp ASC;
                """, (board_id,))
                rows = cursor.fetchall()
                messages = [{
                    "timestamp": row[0],
                    "author": row[1],
                    "content": row[2]
                } for row in rows]
                return messages
            except Exception as e:
                RNS.log(f"[BoardsManager] Error listing messages for '{board_name}': {e}", RNS.LOG_ERROR)
                return []
            finally:
                conn.close()

    def delete_board(self, board_name):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM boards WHERE name = ?;", (board_name,))
                if cursor.rowcount == 0:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.", RNS.LOG_ERROR)
                    return False
                else:
                    conn.commit()
                    RNS.log(f"[BoardsManager] Deleted board '{board_name}' and all its messages", RNS.LOG_DEBUG)
                    return True
            except Exception as e:
                RNS.log(f"[BoardsManager] Error deleting board '{board_name}': {e}", RNS.LOG_ERROR)
                return False
            finally:
                conn.close()
