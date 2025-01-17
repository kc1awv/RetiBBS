import RNS

class ChatRoom:
    def __init__(self, name, chat_manager):
        self.name = name
        self.clients = set()
        self.chat_manager = chat_manager

    def add_client(self, user_hash):
        """
        Add a client to the chat room.
        :param user_hash: The user's hash.
        """
        self.clients.add(user_hash)

    def remove_client(self, user_hash):
        """
        Remove a client from the chat room.
        :param user_hash: The user's hash.
        """
        self.clients.discard(user_hash)
        return len(self.clients) == 0

    def broadcast(self, message, sender=None):
        """
        Broadcast a message to all clients in the chat room.
        :param message: The message to broadcast.
        :param sender: The hash of the user who sent the message.
        """
        for user_hash in self.clients:
            if user_hash != sender:
                self.chat_manager.broadcast_to_user(user_hash, f"[{self.name}] {message}")
                RNS.log(f"[ChatRoom] Broadcast to {user_hash}: {message}", RNS.LOG_DEBUG)

class ChatManager:
    def __init__(self, users_manager, reply_manager, lxmf_handler, theme_manager):
        self.rooms = {}
        self.user_links = {}
        self.users_mgr = users_manager
        self.theme_mgr = theme_manager
        self.lxmf_handler = lxmf_handler
        self.reply_handler = reply_manager
    
    def register_user_link(self, user_hash, link):
        """
        Register a user link.
        :param user_hash: The user's hash.
        :param link: The link to register.
        """
        self.user_links[user_hash] = link
        RNS.log(f"[ChatManager] Registered user link: {user_hash} -> {link}", RNS.LOG_DEBUG)
    
    def unregister_user_link(self, user_hash):
        """
        Unregister a user link.
        :param user_hash: The user's hash.
        """
        if user_hash in self.user_links:
            del self.user_links[user_hash]
            RNS.log(f"[ChatManager] Unregistered user link: {user_hash}", RNS.LOG_DEBUG)
    
    def broadcast_to_user(self, user_hash, message):
        """
        Broadcast a message to a user.
        :param user_hash: The user's hash.
        :param message: The message to broadcast.
        """
        link = self.user_links.get(user_hash)
        if link:
            self.reply_handler.send_link_reply(link, message)
        else:
            RNS.log(f"[ChatManager] Failed to broadcast to {user_hash}: No link found.", RNS.LOG_WARNING)

    def handle_chat_commands(self, command, packet, user_hash):
        """
        Handle chat commands.
        :param command: The command to handle.
        :param packet: The incoming packet.
        :param user_hash: The user's hash.
        """
        tokens = command.split(None, 1)
        if not tokens:
            self.reply_handler.send_link_reply(packet.link, "UNKNOWN COMMAND\n")
            return
        cmd = tokens[0].lower()
        remainder = tokens[1] if len(tokens) > 1 else ""
        if cmd in ["/?", "/help"]:
            self.handle_help(packet, user_hash)
        elif cmd in ["/b", "/back"]:
            self.handle_back(packet, user_hash)
        elif cmd in ["/j", "/join"]:
            self.handle_join_room(packet, remainder, user_hash)
        elif cmd in ["/l", "/leave"]:
            self.handle_leave_room(packet, remainder, user_hash)
        elif cmd in ["/list"]:
            self.handle_list_rooms(packet, user_hash)
        else:
            self.handle_chat_message(packet, command, user_hash)
    
    def handle_help(self, packet, user_hash):
        """
        Show the help screen.
        :param packet: The incoming packet.
        """
        user = self.users_mgr.get_user(user_hash)
        help_text = (
            "Available Chat Commands:\n"
            "  /? - Show this help screen\n"
            "  /back - Return to the main menu\n"
            "  /join <room_name> - Join a chat room\n"
            "  /leave - Leave the current chat room\n"
            "  /list - List available chat rooms\n"
            "  /msg <message> - Send a message to the current chat room\n"
        )
        self.reply_handler.send_resource_reply(packet.link, help_text)

    def handle_back(self, packet, user_hash):
        """
        Return to the main menu.
        :param packet: The incoming packet.
        :param user_hash: The user's hash.
        """
        self.leave_room(user_hash)
        self.unregister_user_link(user_hash)
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
    
    def handle_join_room(self, packet, room_name, user_hash):
        """
        Join a chat room.
        :param packet: The incoming packet.
        :param room_name: The name of the chat room to join.
        :param user_hash: The user's hash.
        """
        room_name = room_name.strip()
        self.leave_room(user_hash)
        room = self.join_room(user_hash, room_name)
        user_display_name = self.users_mgr.get_user_display(user_hash)
        room.broadcast(f"{user_display_name} has joined the room.")
        self.reply_handler.send_link_reply(packet.link, f"Joined room: {room_name}")

    def handle_leave_room(self, packet, _, user_hash):
        """
        Leave the current chat room.
        :param packet: The incoming packet.
        :param user_hash: The user's hash.
        """
        current_room_name = self.users_mgr.get_user_room(user_hash)
        user_display_name = self.users_mgr.get_user_display(user_hash)
        if current_room_name:
            self.leave_room(user_hash)
            self.reply_handler.send_link_reply(packet.link, f"Left room: {current_room_name}")
            room = self.rooms.get(current_room_name)
            if room:
                room.broadcast(f"{user_display_name} has left the room.")
        else:
            self.reply_handler.send_link_reply(packet.link, "You are not in a chat room.")
    
    def handle_list_rooms(self, packet, user_hash):
        """
        List available chat rooms.
        :param packet: The incoming packet.
        """
        if not self.rooms:
            self.reply_handler.send_link_reply(packet.link, "No chat rooms are currently open.\n\n /join <room_name> to create a new room.")
            return
        room_list = "Available Chat Rooms:\n"
        for room_name, room in self.rooms.items():
            participant_count = len(room.clients)
            room_list += f"  - {room_name} ({participant_count} participant{'s' if participant_count != 1 else ''})\n"
        self.reply_handler.send_link_reply(packet.link, room_list)
    
    def handle_chat_message(self, packet, message, user_hash):
        """
        Handle a chat message.
        :param packet: The incoming packet.
        :param message: The message to send.
        :param user_hash: The user's hash.
        """
        current_room_name = self.users_mgr.get_user_room(user_hash)
        if current_room_name:
            room = self.rooms.get(current_room_name)
            if room:
                user_display_name = self.users_mgr.get_user_display(user_hash)
                room.broadcast(f"{user_display_name}: {message.strip()}", sender=user_hash)
                RNS.log(f"[ChatManager] Broadcast to {current_room_name}: {message.strip()}", RNS.LOG_DEBUG)
                self.reply_handler.send_link_reply(packet.link, f"[{current_room_name}] (You): {message.strip()}")
            else:
                self.reply_handler.send_link_reply(packet.link, "ERROR: Chat room not found.")
        else:
            self.reply_handler.send_link_reply(packet.link, "You are not in a chat room.")

    def get_or_create_room(self, room_name):
        """
        Get or create a chat room.
        :param room_name: The name of the chat room.
        """
        if room_name not in self.rooms:
            self.rooms[room_name] = ChatRoom(room_name, self)
        return self.rooms[room_name]

    def join_room(self, user_hash, room_name):
        """
        Join a chat room.
        :param user_hash: The user's hash.
        :param room_name: The name of the chat room to join.
        """
        room = self.get_or_create_room(room_name)
        room.add_client(user_hash)
        self.users_mgr.set_user_room(user_hash, room_name)
        self.reply_handler.send_room_update(self.user_links[user_hash], room_name)
        return room

    def leave_room(self, user_hash):
        """
        Leave the current chat room.
        :param user_hash: The user's hash.
        """
        current_room_name = self.users_mgr.get_user_room(user_hash)
        if current_room_name:
            room = self.rooms[current_room_name]
            user_display_name = self.users_mgr.get_user_display(user_hash)
            if room:
                is_empty = room.remove_client(user_hash)
                room.broadcast(f"{user_display_name} has left the room.")
                if is_empty:
                    del self.rooms[current_room_name]
                    RNS.log(f"[ChatManager] Removed empty room: {current_room_name}", RNS.LOG_DEBUG)
            self.users_mgr.set_user_room(user_hash, None)
