class MainMenuHandler:
    def __init__(self, users_manager, reply_handler, theme_manager):
        self.users_mgr = users_manager
        self.reply_handler = reply_handler
        self.theme_mgr = theme_manager

    def handle_main_menu_commands(self, command, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)
        user_display_name = user.get("name", user_hash)
        tokens = command.split(None, 1)
        if not tokens:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND\n")
            return
        cmd = tokens[0].lower()
        remainder = tokens[1] if len(tokens) > 1 else ""

        if cmd in ["?", "help"]:
            reply = (
                "You are in the main menu.\n\n"
                "Available Commands:\n"
                "  ?  | help        - Show this help text\n"
                "  h  | hello       - Check authorization\n"
                "  n  | name <name> - Set display name\n"
                "  b  | boards      - Switch to boards area\n"
                "  lo | logout      - Log out"
            )
            if user.get("is_admin", False):
                reply += (
                    "\n\nAdmin Commands:\n"
                    "  lu | listusers         - List all users\n"
                    "  a  | admin <user_hash> - Assign admin rights to a user"
                )
            self.reply_handler.send_resource_reply(packet.link, reply)
        elif cmd in ["h", "hello"]:
            reply = f"Hello, {user_display_name}."
            if user.get("is_admin", False):
                reply += "\nYou have ADMIN rights."
            self.reply_handler.send_link_reply(packet.link, reply)
        elif cmd in ["n", "name"]:
            proposed_name = remainder.strip()
            if not proposed_name:
                self.reply_handler.send_link_reply(packet.link, "NAME command requires a non-empty name.")
                return
            if self.users_mgr.is_name_taken(proposed_name, exclude_hash_hex=user_hash):
                self.reply_handler.send_link_reply(packet.link, f"ERROR: The name '{proposed_name}' is already taken.")
                return
            self.users_mgr.update_user(user_hash, name=proposed_name)
            self.reply_handler.send_link_reply(packet.link, f"Your display name is now set to '{proposed_name}'.")
        elif cmd in ["b", "boards"]:
            if self.users_mgr.get_user_area(user_hash) != "boards":
                self.reply_handler.send_clear_screen(packet.link)
                boards_menu_message = self.theme_mgr.theme_files.get("boards_menu.txt", "Boards Menu: [?] Help [b] Back [lb] List Boards [cb] Change Board [p] Post Message [lm] List Messages")
                self.reply_handler.send_resource_reply(packet.link, boards_menu_message)
                self.users_mgr.set_user_area(user_hash, area="boards")
            else:
                self.reply_handler.send_link_reply(packet.link, "You are already in the boards area.")
            #self.users_mgr.set_user_area(user_hash, area="boards")
            current_board = user.get("current_board", None)
            self.reply_handler.send_area_update(packet.link, "Message Boards")
            self.reply_handler.send_board_update(packet.link, current_board)
            #self.reply_handler.send_link_reply(packet.link, "Welcome to the boards area. Use '?' for help.")
        elif cmd in ["lo", "logout"]:
            self.reply_handler.send_link_reply(packet.link, "You have been logged out. Goodbye!\n")
            packet.link.teardown()
        elif cmd in ["lu", "listusers"]:
            if not user.get("is_admin", False):
                self.reply_handler.send_link_reply(packet.link, "ERROR: Only admins can list users.")
                return
            user_list = self.users_mgr.list_users()
            if not user_list:
                reply = "No users found."
            else:
                reply = "Users:\n"
                for user in user_list:
                    name = user["name"] if user["name"] else "N/A"
                    admin_status = " (Admin)" if user["is_admin"] else ""
                    reply += f"- {user['hash_hex']} | {name}{admin_status}\n"
            self.reply_handler.send_resource_reply(packet.link, reply)
        elif cmd in ["a", "admin"]:
            if not user.get("is_admin", False):
                self.reply_handler.send_link_reply(packet.link, "ERROR: Only admins can assign admin rights.")
                return
            target_hash = remainder.strip()
            if not target_hash:
                self.reply_handler.send_link_reply(packet.link, "Usage: ADMIN <user_hash>")
                return
            target_user = self.users_mgr.get_user(target_hash)
            if not target_user:
                self.reply_handler.send_link_reply(packet.link, "ERROR: User does not exist.")
                return
            self.users_mgr.update_user(target_hash, is_admin=True)
            self.reply_handler.send_link_reply(packet.link, f"User {self.users_mgr.get_user_display(target_hash)} has been granted admin rights.")
        else:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND. Use '?' for help.")