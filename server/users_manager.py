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
                        current_area TEXT DEFAULT 'main_menu',
                        current_board TEXT,
                        is_admin BOOLEAN DEFAULT 0
                    );
                """)
                conn.commit()
                RNS.log(f"[UsersManager] Database initialized at {self.db_path}", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[UsersManager] Error initializing database: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def is_name_taken(self, name, exclude_hash_hex=None):
        """
        Checks if a name is already taken by another user.

        Args:
            name (str): The name to check.
            exclude_hash_hex (str, optional): A hash_hex to exclude from the check.

        Returns:
            bool: True if the name is taken, False otherwise.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                if exclude_hash_hex:
                    cursor.execute("""
                        SELECT 1 FROM users WHERE name = ? AND hash_hex != ?;
                    """, (name, exclude_hash_hex))
                else:
                    cursor.execute("""
                        SELECT 1 FROM users WHERE name = ?;
                    """, (name,))
                result = cursor.fetchone()
                return result is not None
            except Exception as e:
                RNS.log(f"[UsersManager] Error checking if name is taken: {e}", RNS.LOG_ERROR)
                return False
            finally:
                conn.close()

    def add_user(self, hash_hex, name=None, current_area="main_menu", current_board=None, is_admin=False):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (hash_hex, name, current_area, current_board, is_admin) 
                    VALUES (?, ?, ?, ?, ?);
                """, (hash_hex, name, current_area, current_board, is_admin))
                conn.commit()
                RNS.log(f"[UsersManager] Added user {hash_hex} (Admin: {is_admin}, Area: {current_area})", RNS.LOG_INFO)
            except sqlite3.IntegrityError:
                RNS.log(f"[UsersManager] User {hash_hex} already exists.", RNS.LOG_WARNING)
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
                    SELECT hash_hex, name, current_area, current_board, is_admin FROM users WHERE hash_hex = ?;
                """, (hash_hex,))
                result = cursor.fetchone()
                if result:
                    return {
                        "hash_hex": result[0],
                        "name": result[1],
                        "current_area": result[2],
                        "current_board": result[3],
                        "is_admin": result[4]
                    }
                return None
            except Exception as e:
                RNS.log(f"[UsersManager] Error retrieving user {hash_hex}: {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()
    
    def get_user_display(self, hash_hex):
        """
        Returns the user's name if it exists, otherwise returns the hash_hex.
        """
        user = self.get_user(hash_hex)
        if user and user["name"]:
            return user["name"]
        return RNS.prettyhexrep(bytes.fromhex(hash_hex))
    
    def get_user_area(self, user_hash):
        user = self.get_user(user_hash)
        return user.get("current_area", "main_menu")

    def update_user(self, hash_hex, name=None, current_area=None, current_board=None, is_admin=None):
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                updates = []
                params = []

                if name is not None:
                    updates.append("name = ?")
                    params.append(name)
                
                if current_area is not None:
                    updates.append("current_area = ?")
                    params.append(current_area)
                
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
                    RNS.log(f"[UsersManager] Updated user {hash_hex}", RNS.LOG_DEBUG)
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
