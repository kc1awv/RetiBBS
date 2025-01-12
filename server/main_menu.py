import asyncio

import RNS

class MainMenuHandler:
    def __init__(self, users_manager, reply_handler, lxmf_handler, theme_manager):
        self.users_mgr = users_manager
        self.reply_handler = reply_handler
        self.lxmf_handler = lxmf_handler
        self.theme_mgr = theme_manager

    def handle_main_menu_commands(self, command, packet, user_hash):
        tokens = command.split(None, 1)
        if not tokens:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND\n")
            return
        cmd = tokens[0].lower()
        remainder = tokens[1] if len(tokens) > 1 else ""

        if cmd in ["?", "help"]:
            self.handle_help(packet, user_hash)
        elif cmd in ["h", "hello"]:
            self.handle_hello(packet, user_hash)
        elif cmd in ["n", "name"]:
            self.handle_name(packet, remainder, user_hash)
        elif cmd in ["d", "destination"]:
            self.handle_set_destination_address(packet, remainder, user_hash)
        elif cmd in ["td", "testdestination"]:
            self.handle_test_destination(packet, user_hash)
        elif cmd in ["b", "boards"]:
            self.handle_boards(packet, user_hash)
        elif cmd in ["lo", "logout"]:
            self.handle_logout(packet)
        elif cmd in ["lu", "listusers"]:
            self.handle_list_users(packet, user_hash)
        elif cmd in ["a", "admin"]:
            self.handle_admin(packet, remainder, user_hash)
        else:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND. Use '?' for help.")

    def handle_help(self, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)
        reply = (
            "You are in the main menu.\n\n"
            "Available Commands:\n"
            "  ?  | help                  - Show this help text\n"
            "  h  | hello                 - Check authorization\n"
            "  n  | name <name>           - Set display name\n"
            "  d  | destination <address> - Set LXMF destination address for message board alerts\n"
            "  td | testdestination       - Test LXMF destination address\n"
            "  b  | boards                - Switch to boards area\n"
            "  lo | logout                - Log out"
        )
        if user.get("is_admin", False):
            reply += (
                "\n\nAdmin Commands:\n"
                "  lu | listusers         - List all users\n"
                "  a  | admin <user_hash> - Assign admin rights to a user"
            )
        self.reply_handler.send_resource_reply(packet.link, reply)

    def handle_hello(self, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)
        user_display_name = user.get("name", user_hash)
        reply = f"Hello, {user_display_name}."
        if user.get("is_admin", False):
            reply += "\nYou have ADMIN rights."
        destination_address = user.get("destination_address")
        if destination_address:
            reply += f"\nYour LXMF destination address is: {destination_address}"
        else:
            reply += "\nYou do not have an LXMF destination address set."
        self.reply_handler.send_link_reply(packet.link, reply)

    def handle_name(self, packet, remainder, user_hash):
        proposed_name = remainder.strip()
        if not proposed_name:
            self.reply_handler.send_link_reply(packet.link, "NAME command requires a non-empty name.")
            return

        if self.users_mgr.is_name_taken(proposed_name, exclude_hash_hex=user_hash):
            self.reply_handler.send_link_reply(packet.link, f"ERROR: The name '{proposed_name}' is already taken.")
            return

        self.users_mgr.update_user(user_hash, name=proposed_name)
        self.reply_handler.send_link_reply(packet.link, f"Your display name is now set to '{proposed_name}'.")

    def handle_set_destination_address(self, packet, remainder, user_hash):
        """
        Command to set a user's LXMF destination address.
        """
        destination_address = remainder.strip()
        if not destination_address:
            self.reply_handler.send_link_reply(packet.link, "Usage: DESTINATION <destination_address>")
            return

        try:
            self.users_mgr.set_user_destination_address(user_hash, destination_address)
            self.reply_handler.send_link_reply(packet.link, "Destination address updated successfully.")
        except Exception as e:
            self.reply_handler.send_link_reply(packet.link, f"Error updating destination address: {e}")

    def handle_test_destination(self, packet, user_hash):
        """
        Test the LXMF message delivery to the user's destination address.
        """
        user = self.users_mgr.get_user(user_hash)
        destination_address = user.get("destination_address")

        if not destination_address:
            self.reply_handler.send_link_reply(packet.link, "You do not have an LXMF destination address set. Use the 'destination' command to set one.")
            return

        try:
            test_subject = "LXMF Test Message"
            test_body = "This is a test message sent from the RetiBBS Server."

            # Queue the message for delivery
            asyncio.run(self.lxmf_handler.enqueue_message(destination_address, test_subject, test_body))
            self.reply_handler.send_link_reply(packet.link, "Test LXMF message has been queued for delivery.")
        except Exception as e:
            RNS.log(f"[MainMenuHandler] Error sending test LXMF message: {e}", RNS.LOG_ERROR)
            self.reply_handler.send_link_reply(packet.link, f"Error sending test LXMF message: {e}")

    def handle_boards(self, packet, user_hash):
        if self.users_mgr.get_user_area(user_hash) != "boards":
            self.reply_handler.send_clear_screen(packet.link)
            boards_menu_message = self.theme_mgr.theme_files.get("header.txt", "Welcome to the Message Boards!")
            boards_menu_message += "\n"
            boards_menu_message += self.theme_mgr.theme_files.get(
                "boards_menu.txt", 
                "Boards Menu: [?] Help [b] Back [lb] List Boards [cb] Change Board [p] Post Message [lm] List Messages"
            )
            self.reply_handler.send_resource_reply(packet.link, boards_menu_message)
            self.users_mgr.set_user_area(user_hash, area="boards")
        else:
            self.reply_handler.send_link_reply(packet.link, "You are already in the boards area.")
        current_board = self.users_mgr.get_user_board(user_hash)
        self.reply_handler.send_area_update(packet.link, "Message Boards")
        self.reply_handler.send_board_update(packet.link, current_board)

    def handle_logout(self, packet):
        self.reply_handler.send_link_reply(packet.link, "You have been logged out. Goodbye!\n")
        packet.link.teardown()
    
    def handle_list_users(self, packet, user_hash):
        user = self.users_mgr.get_user(user_hash)
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
    
    def handle_admin(self, packet, remainder, user_hash):
        user = self.users_mgr.get_user(user_hash)
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
        target_display_name = self.users_mgr.get_user_display(target_hash)
        self.reply_handler.send_link_reply(packet.link, f"User {target_display_name} has been granted admin rights.")