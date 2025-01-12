import math
import time
import sqlite3
import threading

from datetime import datetime, timezone

import RNS

class BoardsManager:
    def __init__(self, users_manager, reply_manager, theme_manager, db_path='boards.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.users_mgr = users_manager
        self.theme_mgr = theme_manager
        self.reply_handler = reply_manager
        self.user_pages = {}
        self._initialize_database()

    def _initialize_database(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS boards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        board_id INTEGER NOT NULL,
                        timestamp REAL NOT NULL,
                        author TEXT NOT NULL,
                        topic TEXT NOT NULL DEFAULT 'No Topic',
                        content TEXT NOT NULL,
                        parent_id INTEGER DEFAULT NULL,
                        FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
                    );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS read_messages (
                    user_hash TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY (user_hash, message_id),
                    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
                );
                """)
                conn.commit()
                RNS.log(f"[BoardsManager] Database initialized at {self.db_path}", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[BoardsManager] Error initializing database: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()
    
    def handle_board_commands(self, command, packet, user_hash):
        tokens = command.split(None, 1)
        if not tokens:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND\n")
            return
        cmd = tokens[0].lower()
        remainder = tokens[1] if len(tokens) > 1 else ""
        if cmd in ["?", "help"]:
            self.handle_help(packet, user_hash)
        elif cmd in ["b", "back"]:
            self.handle_back(packet, user_hash)
        elif cmd in ["lb", "listboards"]:
            self.handle_list_boards(packet)
        elif cmd in ["cb", "changeboard"]:
            board_name = remainder.strip()
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "Usage: CHANGEBOARD <board_name>")
                return
            self.handle_change_board(packet, user_hash, board_name)
        elif cmd in ["p", "post"]:
            self.handle_post_message(packet, remainder, user_hash)
        elif cmd in ["lm", "listmessages"]:
            self.handle_list_messages(packet, remainder, user_hash)
        elif cmd in ["lu", "listunread"]:
            self.handle_list_unread_messages(packet, user_hash)
        elif cmd in [">", "next"]:
            self.handle_next_page(packet, user_hash)
        elif cmd in ["<", "prev"]:
            self.handle_prev_page(packet, user_hash)
        elif cmd in ["r", "read"]:
            message_id = remainder.strip()
            if not message_id:
                self.reply_handler.send_link_reply(packet.link, "Usage: READ <message_id>")
                return
            self.handle_read_message(packet, message_id, user_hash)
        elif cmd in ["re", "reply"]:
            self.handle_reply(packet, remainder, user_hash)
        elif cmd in ["nb", "newboard"]:
            self.handle_new_board(packet, remainder, user_hash)
        elif cmd in ["db", "deleteboard"]:
            self.handle_delete_board(packet, remainder, user_hash)
        else:
            self.reply_handler.send_link_reply(packet.link, f"Unknown command: {cmd} in board area.")
    
    def handle_help(self, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)
        reply = (
            "You are in the message boards area.\n\n"
            "Available Commands:\n"
            "  ?  | help                           - Show this help text\n"
            "  b  | back                           - Return to main menu\n"
            "  lb | listboards                     - List all boards\n"
            "  cb | changeboard <boardname>        - Switch to a board (so you can post/list by default)\n"
            "  p  | post <text>                    - Post a message to your current board\n"
            "  lm | listmessages \[boardname]       - List messages in 'boardname' or your current board\n"
            "  lu | listunread                     - List unread messages in your current board\n"
            "  >  | next                           - Go to the next page of messages\n"
            "  <  | prev                           - Go to the previous page of messages\n"
            "  r  | read <message_id>              - Read a message by ID\n"
            "  re | reply <message_id> | <content> - Reply to a message by ID\n"
        )
        if user.get("is_admin", False):
            reply += (
                "\n\nAdmin Commands:\n"
                "  nb | newboard <name>          - Create a new board\n"
                "  db | deleteboard <boardname>  - Delete a board\n"
            )
        self.reply_handler.send_resource_reply(packet.link, reply)

    def handle_back(self, packet, user_hash):
        self.reply_handler.send_clear_screen(packet.link)
        self.users_mgr.set_user_area(user_hash, area="main_menu")
        main_menu_message = self.theme_mgr.theme_files.get("header.txt", "Welcome to RetiBBS")
        main_menu_message += "\n"
        main_menu_message += self.theme_mgr.theme_files.get(
            "main_menu.txt",
            "Main Menu: [?] Help [h] Hello [n] Name [b] Boards Area [lo] Log Out"
            )
        self.reply_handler.send_resource_reply(packet.link, main_menu_message)
        self.reply_handler.send_area_update(packet.link, "Main Menu")

    def handle_list_boards(self, packet):
        names = self.list_boards()
        if not names:
            reply = "No boards exist."
        else:
            reply = "All Boards:\n" + "\n".join(names) + "\n"
        self.reply_handler.send_resource_reply(packet.link, reply)

    def board_exists(self, board_name):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                return result is not None
            except Exception as e:
                RNS.log(f"[BoardsManager] Error checking if board '{board_name}' exists: {e}", RNS.LOG_ERROR)
                return False
            finally:
                conn.close()

    def handle_change_board(self, packet, user_hash, board_name):
        board_exists = self.board_exists(board_name)
        current_board = self.users_mgr.get_user_board(user_hash)
        if not board_exists:
            if current_board:
                reply = f"ERROR: Board '{board_name}' does not exist. You are still in board '{current_board}'"
            else:
                reply = f"ERROR: Board '{board_name}' does not exist. You are not currently in any board."
            self.reply_handler.send_link_reply(packet.link, reply)
            return
        if current_board == board_name:
            reply = f"You are already in board '{board_name}'"
        else:
            self.users_mgr.set_user_board(user_hash, board_name)
            reply = f"You have joined board '{board_name}'"
            reply += "\n\nCommands: 'lm' to list messages, 'lu' to list unread messages."
        self.reply_handler.send_board_update(packet.link, board_name)
        self.reply_handler.send_link_reply(packet.link, reply)

    def handle_list_messages(self, packet, remainder, user_hash, page=None, page_size=10):
        board_name = remainder.strip()
        if not board_name:
            board_name = self.users_mgr.get_user_board(user_hash)
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "You are not in any board. Use CHANGEBOARD <board> first.")
                return
        current_page = page or self.user_pages.get(user_hash, 1)
        try:
            posts, total_messages = self.list_messages(board_name, page=current_page)
            total_pages = math.ceil(total_messages / page_size)
            if not posts:
                reply = f"No messages found in board '{board_name}'."
            else:
                lines = [f"Messages in board '{board_name}' (Page {current_page}/{total_pages}):"]
                for message in posts:
                    timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message["timestamp"]))
                    lines.append(
                        f"[{message['id']}] {timestamp_str} | {message['author']} | {message['topic']} "
                        f"({message['reply_count']} replies)"
                    )
                lines.append("\nCommands: 'r <id>' to read a message, < (prev) || > (next) for navigation.")
                reply = "\n".join(lines)
            self.reply_handler.send_resource_reply(packet.link, reply)
        except Exception as e:
            RNS.log(f"[BoardsManager] Error listing messages for board '{board_name}': {e}", RNS.LOG_ERROR)
            self.reply_handler.send_link_reply(packet.link, f"Error listing messages for board '{board_name}': {e}")

    def handle_list_unread_messages(self, packet, user_hash):
        board_name = self.users_mgr.get_user_board(user_hash)
        if not board_name:
            self.reply_handler.send_link_reply(packet.link, "You are not in any board. Use CHANGEBOARD <board> first.")
            return
        unread_messages = self.list_unread_messages(board_name, user_hash)
        if not unread_messages:
            reply = f"No unread messages in board '{board_name}'."
        else:
            lines = [f"Unread messages in board '{board_name}':"]
            for m in unread_messages:
                t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["timestamp"]))
                lines.append(f"[{m['id']}] {t_str} | {m['author']} | {m['topic']}")
            reply = "\n".join(lines)
        self.reply_handler.send_resource_reply(packet.link, reply)

    def handle_next_page(self, packet, user_hash):
        current_board = self.users_mgr.get_user_board(user_hash)
        if not current_board:
            self.reply_handler.send_link_reply(packet.link, "You are not in any board. Use CHANGEBOARD <board> first.")
            return
        current_page = self.user_pages.get(user_hash, 1)
        posts, total_messages = self.list_messages(current_board, page=current_page + 1)
        if not posts:
            self.reply_handler.send_link_reply(packet.link, "You are already on the last page.")
        else:
            self.user_pages[user_hash] = current_page + 1
            self.handle_list_messages(packet, current_board, page=current_page + 1)

    def handle_prev_page(self, packet, user_hash):
        current_board = self.users_mgr.get_user_board(user_hash)
        if not current_board:
            self.reply_handler.send_link_reply(packet.link, "You are not in any board. Use CHANGEBOARD <board> first.")
            return
        current_page = self.user_pages.get(user_hash, 1)
        if current_page <= 1:
            self.reply_handler.send_link_reply(packet.link, "You are already on the first page.")
        else:
            self.user_pages[user_hash] = current_page - 1
            self.handle_list_messages(packet, current_board, page=current_page - 1)

    def handle_read_message(self, packet, message_id, user_hash):
        try:
            message = self.get_message_by_id(message_id)
            if message:
                t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message["timestamp"]))
                reply = (
                    f"\n[bold]----- Message {message_id} -----[/]\n"
                    f"Timestamp: {t_str}\n"
                    f"Author: {message['author']}\n"
                    f"Topic: {message['topic']}\n"
                    "\n"
                    f"{message['content']}\n"
                )
                replies = self.list_replies(message_id)
                if replies:
                    reply += "\nReplies:\n"
                    for r in replies:
                        r_t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["timestamp"]))
                        reply += f"  [{r['id']}] {r_t_str} | {r['author']}: {r['content']}\n"
                reply += "\nTo reply, use: reply <message_id> | <content>"
                self.mark_message_as_read(user_hash, message_id)
            else:
                reply = f"Message ID {message_id} not found."
        except Exception as e:
            reply = f"Error reading message ID {message_id}: {e}"
            RNS.log(f"[BoardsManager] Error reading message ID {message_id}: {e}", RNS.LOG_ERROR)
        self.reply_handler.send_resource_reply(packet.link, reply)

    def mark_message_as_read(self, user_hash, message_id):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO read_messages (user_hash, message_id)
                    VALUES (?, ?);
                """, (user_hash, message_id))
                conn.commit()
                RNS.log(f"[BoardsManager] User {user_hash} marked message {message_id} as read.", RNS.LOG_DEBUG)
            except Exception as e:
                RNS.log(f"[BoardsManager] Error marking message {message_id} as read for user {user_hash}: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()
    
    def handle_post_message(self, packet, remainder, user_hash):
        post_text = remainder.strip()
        if not post_text:
            self.reply_handler.send_link_reply(packet.link, "Usage: POST <topic> | <message content>")
            return
        if "|" not in post_text:
            self.reply_handler.send_link_reply(packet.link, "ERROR: Please use '|' to separate the topic and content.\nExample: POST My Topic | This is the message content.")
            return
        topic, content = map(str.strip, post_text.split("|", 1))
        if not topic:
            self.reply_handler.send_link_reply(packet.link, "ERROR: Topic cannot be empty.")
            return
        if not content:
            self.reply_handler.send_link_reply(packet.link, "ERROR: Message content cannot be empty.")
            return
        user_info = self.users_mgr.get_user(user_hash)
        if not user_info:
            self.reply_handler.send_link_reply(packet.link, "[ERROR] User not found.")
            RNS.log(f"[BoardsManager] Received 'p' from unknown user: {user_hash}", RNS.LOG_ERROR)
            return
        author = user_info.get("name") or user_hash
        board_name = self.users_mgr.get_user_board(user_hash)
        if not board_name:
            self.reply_handler.send_link_reply(packet.link, "You are not in a board area.")
            return
        try:
            self.post_message(board_name, author, topic, content)
            reply = f"Posted to board '{board_name}': [{topic}] {content}"
            self.reply_handler.send_link_reply(packet.link, reply)
        except Exception as e:
            self.reply_handler.send_link_reply(packet.link, f"Error posting to board '{board_name}': {e}")
    
    def handle_reply(self, packet, remainder, user_hash):
        if "|" not in remainder:
            self.reply_handler.send_link_reply(packet.link, "Usage: REPLY <message_id> | <content>")
            return
        try:
            message_id_str, content = map(str.strip, remainder.split("|", 1))
            message_id = int(message_id_str)
            if not content:
                self.reply_handler.send_link_reply(packet.link, "ERROR: Reply content cannot be empty.")
                return
            parent_message = self.get_message_by_id(message_id)
            if not parent_message:
                self.reply_handler.send_link_reply(packet.link, f"Message ID {message_id} not found.")
                return
            board_name = self.users_mgr.get_user_board(user_hash)
            if not board_name:
                self.reply_handler.send_link_reply(packet.link, "You are not in a board area.")
                return
            user_info = self.users_mgr.get_user(user_hash)
            author = user_info.get("name") or user_hash
            topic = f"Re: {parent_message['topic']}"
            self.post_message(board_name, author, topic, content, parent_id=message_id)
            self.reply_handler.send_link_reply(packet.link, f"Reply posted to message ID {message_id}.")
        except ValueError:
            self.reply_handler.send_link_reply(packet.link, "Usage: REPLY <message_id> | <content>")
        except Exception as e:
            self.reply_handler.send_link_reply(packet.link, f"Error replying to message ID {message_id}: {e}")
            RNS.log(f"[BoardsManager] Error in reply command: {e}", RNS.LOG_ERROR)
    
    def handle_new_board(self, packet, remainder, user_hash):
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
    
    def handle_delete_board(self, packet, remainder, user_hash):
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

    def is_valid_board_name(self, board_name):
        return board_name.isalnum() and 3 <= len(board_name) <= 20

    def post_message(self, board_name, author, topic, content, parent_id=None):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                if not result:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.", RNS.LOG_ERROR)
                else:
                    board_id = result[0]
                timestamp = datetime.now(timezone.utc).timestamp()
                cursor.execute("""
                    INSERT INTO messages (board_id, timestamp, author, topic, content, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (board_id, timestamp, author, topic, content, parent_id))
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

    def list_messages(self, board_name, page=1, page_size=10):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                if not result:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.", RNS.LOG_ERROR)
                    return [], 0
                board_id = result[0]
                offset = (page - 1) * page_size
                cursor.execute("""
                    SELECT m.id, m.timestamp, m.author, m.topic, m.content,
                           (SELECT COUNT(*) FROM messages r WHERE r.parent_id = m.id) AS reply_count
                    FROM messages m
                    WHERE m.board_id = ? AND m.parent_id IS NULL
                    ORDER BY m.timestamp DESC
                    LIMIT ? OFFSET ?;
                """, (board_id, page_size, offset))
                rows = cursor.fetchall()
                cursor.execute("""
                    SELECT COUNT(*) FROM messages
                    WHERE board_id = ? AND parent_id IS NULL;
                """, (board_id,))
                total_messages = cursor.fetchone()[0]

                messages = [{
                    "id": row[0],
                    "timestamp": row[1],
                    "author": row[2],
                    "topic": row[3],
                    "content": row[4],
                    "reply_count": row[5]
                } for row in rows]
                return messages, total_messages
            except Exception as e:
                RNS.log(f"[BoardsManager] Error listing messages for '{board_name}': {e}", RNS.LOG_ERROR)
                return [], 0
            finally:
                conn.close()

    def list_unread_messages(self, board_name, user_hash):
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
                    SELECT m.id, m.timestamp, m.author, m.topic, m.content
                    FROM messages m
                    LEFT JOIN read_messages r
                    ON m.id = r.message_id AND r.user_hash = ?
                    WHERE m.board_id = ? AND m.parent_id IS NULL AND r.message_id IS NULL
                    ORDER BY m.timestamp DESC;
                """, (user_hash, board_id))
                rows = cursor.fetchall()
                messages = [{
                    "id": row[0],
                    "timestamp": row[1],
                    "author": row[2],
                    "topic": row[3],
                    "content": row[4]
                } for row in rows]
                return messages
            except Exception as e:
                RNS.log(f"[BoardsManager] Error listing unread messages for board '{board_name}': {e}", RNS.LOG_ERROR)
                return []
            finally:
                conn.close()

    def get_message_by_id(self, message_id):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT timestamp, author, topic, content FROM messages
                    WHERE id = ?;
                """, (message_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "timestamp": row[0],
                        "author": row[1],
                        "topic": row[2],
                        "content": row[3]
                    }
                return None
            except Exception as e:
                RNS.log(f"[BoardsManager] Error retrieving message ID {message_id}: {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()
    
    def list_replies(self, parent_id):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, timestamp, author, content FROM messages
                    WHERE parent_id = ?
                    ORDER BY timestamp ASC;
                """, (parent_id,))
                rows = cursor.fetchall()
                replies = [{
                    "id": row[0],
                    "timestamp": row[1],
                    "author": row[2],
                    "content": row[3]
                } for row in rows]
                return replies
            except Exception as e:
                RNS.log(f"[BoardsManager] Error listing replies for message ID {parent_id}: {e}", RNS.LOG_ERROR)
                return []
            finally:
                conn.close()

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
