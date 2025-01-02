import sqlite3
import threading

import RNS

class UsersManager:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._initialize_database()

    def _initialize_database(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hash_hex TEXT UNIQUE NOT NULL,
                        name TEXT,
                        current_board TEXT,
                        is_admin BOOLEAN DEFAULT 0
                    );
                """)
                conn.commit()
                RNS.log(f"[UsersManager] Database initialized at {self.db_path}")
            except Exception as e:
                RNS.log(f"[UsersManager] Error initializing database: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def add_user(self, hash_hex, name=None, current_board=None, is_admin=False):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (hash_hex, name, current_board, is_admin) 
                    VALUES (?, ?, ?, ?);
                """, (hash_hex, name, current_board, is_admin))
                conn.commit()
                RNS.log(f"[UsersManager] Added user {hash_hex} (Admin: {is_admin})")
            except sqlite3.IntegrityError:
                RNS.log(f"[UsersManager] User {hash_hex} already exists.")
            except Exception as e:
                RNS.log(f"[UsersManager] Error adding user {hash_hex}: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def get_user(self, hash_hex):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT hash_hex, name, current_board, is_admin FROM users WHERE hash_hex = ?;
                """, (hash_hex,))
                result = cursor.fetchone()
                if result:
                    return {"hash_hex": result[0], "name": result[1], "current_board": result[2], "is_admin": result[3]}
                return None
            except Exception as e:
                RNS.log(f"[UsersManager] Error retrieving user {hash_hex}: {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()

    def update_user(self, hash_hex, name=None, current_board=None, is_admin=None):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                updates = []
                params = []

                if name is not None:
                    updates.append("name = ?")
                    params.append(name)
                
                if current_board is not None:
                    updates.append("current_board = ?")
                    params.append(current_board)

                if is_admin is not None:
                    updates.append("is_admin = ?")
                    params.append(is_admin)

                if updates:
                    params.append(hash_hex)
                    cursor.execute(f"""
                        UPDATE users SET {", ".join(updates)} WHERE hash_hex = ?;
                    """, tuple(params))
                    conn.commit()
                    RNS.log(f"[UsersManager] Updated user {hash_hex}")
            except Exception as e:
                RNS.log(f"[UsersManager] Error updating user {hash_hex}: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def list_users(self):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT hash_hex, name, is_admin FROM users;")
                return [{"hash_hex": row[0], "name": row[1], "is_admin": row[2]} for row in cursor.fetchall()]
            except Exception as e:
                RNS.log(f"[UsersManager] Error listing users: {e}", RNS.LOG_ERROR)
                return []
            finally:
                conn.close()
