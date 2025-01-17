import sqlite3
import threading

import RNS

class UsersManager:
    def __init__(self, db_path='users.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.user_sessions = {}
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
                        destination_address TEXT DEFAULT NULL,
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
        :param name: The name to check.
        :param exclude_hash_hex: Optional hash_hex to exclude from the check.
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

    def add_user(self, hash_hex, name=None, is_admin=False):
        """
        Add a new user to the database.
        :param hash_hex: The user's hash_hex.
        :param name: Optional display name.
        :param is_admin: Optional admin flag.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (hash_hex, name, is_admin) 
                    VALUES (?, ?, ?);
                """, (hash_hex, name, is_admin))
                conn.commit()
                RNS.log(f"[UsersManager] Added user {hash_hex} (Admin: {is_admin})", RNS.LOG_INFO)
            except sqlite3.IntegrityError:
                RNS.log(f"[UsersManager] User {hash_hex} already exists.", RNS.LOG_WARNING)
            except Exception as e:
                RNS.log(f"[UsersManager] Error adding user {hash_hex}: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def get_user(self, hash_hex):
        """
        Retrieve a user by their hash_hex.
        :param hash_hex: The user's hash_hex.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT hash_hex, name, destination_address, is_admin FROM users WHERE hash_hex = ?;
                """, (hash_hex,))
                result = cursor.fetchone()
                if result:
                    return {
                        "hash_hex": result[0],
                        "name": result[1],
                        "destination_address": result[2],
                        "is_admin": result[3]
                    }
                return None
            except Exception as e:
                RNS.log(f"[UsersManager] Error retrieving user {hash_hex}: {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()
    
    def get_user_by_name(self, name):
        """
        Retrieve a user by their name.
        :param name: The user's name
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT hash_hex, name, destination_address, is_admin FROM users WHERE name = ?;
                """, (name,))
                row = cursor.fetchone()
                if row:
                    return {
                        "hash_hex": row[0],
                        "name": row[1],
                        "destination_address": row[2],
                        "is_admin": row[3]
                    }
                return None
            except Exception as e:
                RNS.log(f"[UsersManager] Error retrieving user by name '{name}': {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()
    
    def get_user_display(self, hash_hex):
        """
        Returns the user's name if it exists, otherwise returns the hash_hex.
        :param hash_hex: The user's hash_hex.
        """
        user = self.get_user(hash_hex)
        if user and user["name"]:
            return user["name"]
        return RNS.prettyhexrep(bytes.fromhex(hash_hex))

    def update_user(self, hash_hex, name=None, is_admin=None):
        """
        Update a user's information.
        :param hash_hex: The user's hash_hex.
        :param name: Optional new display name.
        :param is_admin: Optional new admin flag.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                updates = []
                params = []

                if name is not None:
                    updates.append("name = ?")
                    params.append(name)
                
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
        """
        List all users in the database.
        """
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

    def set_user_destination_address(self, user_hash, destination_address):
        """
        Set a user's LXMF destination address.
        :param user_hash: The user's hash_hex.
        :param destination_address: The destination address.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users
                    SET destination_address = ?
                    WHERE hash_hex = ?;
                """, (destination_address, user_hash))
                conn.commit()
                RNS.log(f"[UsersManager] Updated destination address for user {user_hash}.", RNS.LOG_INFO)
            except Exception as e:
                RNS.log(f"[UsersManager] Error updating destination address for user {user_hash}: {e}", RNS.LOG_ERROR)
            finally:
                conn.close()

    def get_user_destination_address(self, user_hash):
        """
        Retrieve a user's LXMF destination address.
        :param user_hash: The user's hash_hex.
        """
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT destination_address FROM users WHERE hash_hex = ?;
                """, (user_hash,))
                row = cursor.fetchone()
                return row[0] if row else None
            except Exception as e:
                RNS.log(f"[UsersManager] Error retrieving destination address for user {user_hash}: {e}", RNS.LOG_ERROR)
                return None
            finally:
                conn.close()

    def get_user_area(self, user_hash):
        """
        Retrieve the current area for a user.
        :param user_hash: The user's hash_hex.
        """
        if user_hash in self.user_sessions:
            return self.user_sessions[user_hash].get("current_area", "main_menu")
    
    def set_user_area(self, user_hash, area):
        """
        Set the current area for a user.
        :param user_hash: The user's hash_hex.
        """
        if user_hash not in self.user_sessions:
            self.user_sessions[user_hash] = {}
        self.user_sessions[user_hash]["current_area"] = area

    def get_user_board(self, user_hash):
        """
        Retrieve the current board for a user.
        :param user_hash: The user's hash_hex.
        """
        if user_hash in self.user_sessions:
            return self.user_sessions[user_hash].get("current_board", None)
        
    def set_user_board(self, user_hash, board):
        """
        Set the current board for a user.
        :param user_hash: The user's hash_hex.
        :param board: The board name.
        """
        if user_hash not in self.user_sessions:
            self.user_sessions[user_hash] = {}
        self.user_sessions[user_hash]["current_board"] = board

    def remove_user_session(self, user_hash):
        """
        Remove a user's session.
        :param user_hash: The user's hash_hex.
        """
        if user_hash in self.user_sessions:
            del self.user_sessions[user_hash]
        else:
            RNS.log(f"[UsersManager] User {user_hash} does not have an active session.", RNS.LOG_WARNING)