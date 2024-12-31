# boards.py
import time
import sqlite3
import threading

from datetime import datetime, timezone

import RNS

class BoardsManager:
    """
    Manages multiple boards with message persistence using SQLite.
    Each board holds a list of messages.
    """

    def __init__(self, db_path='boards.db'):
        """
        Initialize the BoardsManager.

        Args:
            db_path (str): Path to the SQLite database file.
        """
        self.db_path = db_path
        self.lock = threading.Lock()
        self._initialize_database()

    def _initialize_database(self):
        """
        Initializes the SQLite database and creates necessary tables if they don't exist.
        """
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
                RNS.log(f"[BoardsManager] Database initialized at {self.db_path}")
            except Exception as e:
                RNS.log(f"[BoardsManager] Error initializing database: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def create_board(self, board_name):
        """
        Create a new board if it doesn't already exist.

        Args:
            board_name (str): Name of the board to create.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("INSERT INTO boards (name) VALUES (?);", (board_name,))
                conn.commit()
                RNS.log(f"[BoardsManager] Created new board '{board_name}'")
            except sqlite3.IntegrityError:
                RNS.log(f"[BoardsManager] Board '{board_name}' already exists")
            except Exception as e:
                RNS.log(f"[BoardsManager] Error creating board '{board_name}': {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def post_message(self, board_name, author, content):
        """
        Append a new message to the specified board.

        Args:
            board_name (str): Name of the board to post the message to.
            author (str): Author of the message (e.g., user name or hash).
            content (str): Content of the message.
        """
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
                RNS.log(f"[BoardsManager] New message posted to '{board_name}' by '{author}' at {timestamp} UTC")
            except Exception as e:
                RNS.log(f"[BoardsManager] Error posting message to '{board_name}': {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def list_messages(self, board_name):
        """
        Retrieve all messages for the specified board in chronological order.

        Args:
            board_name (str): Name of the board to list messages from.

        Returns:
            list: List of message dictionaries. Empty list if board doesn't exist.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM boards WHERE name = ?;", (board_name,))
                result = cursor.fetchone()
                if not result:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.")
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

    def list_boards(self):
        """
        Retrieve a list of all existing board names.

        Returns:
            list: List of board names.
        """
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

    def delete_board(self, board_name):
        """
        Delete the specified board and all its messages.

        Args:
            board_name (str): Name of the board to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM boards WHERE name = ?;", (board_name,))
                if cursor.rowcount == 0:
                    RNS.log(f"[BoardsManager] Board '{board_name}' does not exist.")
                    return False
                else:
                    conn.commit()
                    RNS.log(f"[BoardsManager] Deleted board '{board_name}' and all its messages")
                    return True
            except Exception as e:
                RNS.log(f"[BoardsManager] Error deleting board '{board_name}': {e}", RNS.LOG_ERROR)
                return False
            finally:
                conn.close()
