#!/usr/bin/env python3
import argparse
import os
import time
import json
import RNS

from boards import BoardsManager

APP_NAME = "retibbs"
SERVICE_NAME = "bbs"

boards_mgr = BoardsManager()
authorized_users = {}
latest_client_link = None

def load_or_create_identity(identity_path):
    """
    Loads (or creates) the server's own private key Identity.
    """
    if os.path.isfile(identity_path):
        server_identity = RNS.Identity.from_file(identity_path)
        RNS.log(f"[Server] Loaded server Identity from {identity_path}")
    else:
        server_identity = RNS.Identity()
        server_identity.to_file(identity_path)
        RNS.log(f"[Server] Created new server Identity and saved to {identity_path}")
    return server_identity

def load_authorized_users(auth_path):
    """
    Loads authorized users from JSON, returning a dict:
      { <hash_hex>: {"name": <string or None>, "current_board": <str or None> } }
    If file doesn't exist, returns an empty dict.
    """
    if os.path.isfile(auth_path):
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            RNS.log(f"[Server] Could not load authorized users: {e}", RNS.LOG_ERROR)
            return {}
    else:
        return {}

def save_authorized_users(auth_path, user_dict):
    """
    Saves the authorized user dictionary to a JSON file.
    """
    try:
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(user_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        RNS.log(f"[Server] Could not save authorized users: {e}", RNS.LOG_ERROR)

def get_user_display(hash_hex):
    """
    Return the user's name if set, or a pretty hex rep of hash if no name is set.
    """
    if hash_hex in authorized_users:
        user_info = authorized_users[hash_hex]
        if user_info["name"] is not None:
            return user_info["name"]
    short_hash = RNS.prettyhexrep(bytes.fromhex(hash_hex))
    return short_hash

def is_name_taken(name, own_hash_hex=None):
    """
    Check if any other user is using this 'name' (case-sensitive check).
    If own_hash_hex is given, ignore that user.
    """
    for h, info in authorized_users.items():
        if h != own_hash_hex and info["name"] == name:
            return True
    return False

def server_setup(configpath, identity_file, auth_file):
    global authorized_users, boards_mgr

    reticulum = RNS.Reticulum(configpath)
    server_identity = load_or_create_identity(identity_file)
    authorized_users = load_authorized_users(auth_file)
    server_destination = RNS.Destination(
        server_identity,
        RNS.Destination.IN,
        RNS.Destination.SINGLE,
        APP_NAME,
        SERVICE_NAME,
        "server"
    )
    server_destination.set_link_established_callback(client_connected)

    RNS.log(f"[Server] BBS Server running. Identity hash: {RNS.prettyhexrep(server_destination.hash)}")
    RNS.log(f"[Server] Loaded {len(authorized_users)} authorized users.")
    RNS.log("[Server] Press Enter to send an ANNOUNCE. Ctrl-C to quit.")

    while True:
        input()
        server_destination.announce()
        RNS.log("[Server] Sent announce from " + RNS.prettyhexrep(server_destination.hash))

def client_connected(link):
    global latest_client_link
    latest_client_link = link

    RNS.log("[Server] Client link established!")
    link.set_link_closed_callback(client_disconnected)
    link.set_packet_callback(server_packet_received)
    link.set_remote_identified_callback(remote_identified)

    # FUTURE: automatically accept inbound resources from the client:
    # link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
    # link.set_resource_started_callback(resource_started_callback)
    # link.set_resource_concluded_callback(resource_concluded_callback)

def client_disconnected(link):
    RNS.log("[Server] Client disconnected.")

def remote_identified(link, identity):
    """
    Called when the client calls link.identify(client_identity),
    so we know who they are by their public key hash.
    """
    identity_hash_hex = identity.hash.hex()
    display_str = RNS.prettyhexrep(identity.hash)

    RNS.log(f"[Server] Remote identified as {display_str}")

    # For demonstration, automatically authorize them
    if identity_hash_hex not in authorized_users:
        authorized_users[identity_hash_hex] = {
            "name": None,
            "current_board": None
        }
        RNS.log(f"[Server] Added new user {display_str} to authorized list.")
        if auth_file_path:
            save_authorized_users(auth_file_path, authorized_users)
    
    current_board = authorized_users[identity_hash_hex].get("current_board")
    if current_board:
        reply = f"You have joined board '{current_board}'\n"
    else:
        reply = "You are not in any board.\n"

    send_link_reply(link, reply)

def server_packet_received(message_bytes, packet):
    """
    Called when the client sends a PACKET. Large data or resources from the client
    would appear differently. For responding with large data, we use RNS.Resource.
    """
    global authorized_users

    remote_identity = packet.link.get_remote_identity()
    if not remote_identity:
        RNS.log("[Server] Received data from an unidentified peer.")
        return

    identity_hash_hex = remote_identity.hash.hex()
    user_info = authorized_users.get(identity_hash_hex, {})
    user_display_name = get_user_display(identity_hash_hex)

    try:
        msg_str = message_bytes.decode("utf-8").strip()
    except:
        RNS.log("[Server] Error decoding message!")
        return

    RNS.log(f"[Server] Received: {msg_str} from {user_display_name}")

    tokens = msg_str.split(None, 1)
    if not tokens:
        send_link_reply(packet.link, "UNKNOWN COMMAND\n")
        return

    cmd = tokens[0].lower()
    remainder = tokens[1] if len(tokens) > 1 else ""

    is_authorized = (identity_hash_hex in authorized_users)

    if cmd in ["?", "help"]:
        reply = (
            "Available Commands:\n"
            "  ?  | help                     - Show this help text\n"
            "  h  | hello                    - Check authorization\n"
            "  n  | name <name>              - Set display name\n"
            "  lb | listboards               - List all boards\n"
            "  b  | board <boardname>        - Switch to a board (so you can post/list by default)\n"
            "  p  | post <text>              - Post a message to your current board\n"
            "  l  | list [boardname]         - List messages in 'boardname' or your current board\n"
        )
        if user_info.get("is_admin", False):
            reply += (
                "\nAdmin Commands:\n"
                "  cb | createboard <name>       - Create a new board\n"
                "  db | deleteboard <boardname>  - Delete a board\n"
                "  a  | admin <user_hash>        - Assign admin rights to a user\n"
        )
        send_resource_reply(packet.link, reply)
    
    elif cmd in ["h", "hello"]:
        reply = f"Hello, {user_display_name}. You are {'AUTHORIZED' if is_authorized else 'UNAUTHORIZED'}.\n"
        if user_info.get("is_admin", False):
            reply += "You have ADMIN rights.\n"
        send_link_reply(packet.link, reply)

    elif cmd in ["n", "name"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return

        proposed_name = remainder.strip()
        if not proposed_name:
            send_link_reply(packet.link, "NAME command requires a non-empty name.\n")
            return

        if is_name_taken(proposed_name, own_hash_hex=identity_hash_hex):
            send_link_reply(packet.link, f"ERROR: The name '{proposed_name}' is already taken.\n")
            return

        authorized_users[identity_hash_hex]["name"] = proposed_name
        send_link_reply(packet.link, f"Your display name is now set to '{proposed_name}'.\n")

        if auth_file_path:
            save_authorized_users(auth_file_path, authorized_users)
    
    elif cmd in ["lb", "listboards"]:
        handle_list_boards(packet)

    elif cmd in ["b", "board"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return

        board_name = remainder.strip()
        if not board_name:
            send_link_reply(packet.link, "Usage: BOARD <board_name>\n")
            return

        handle_join_board(packet, identity_hash_hex, board_name)

    elif cmd in ["p", "post"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return

        post_text = remainder.strip()
        if not post_text:
            send_link_reply(packet.link, "Usage: POST <text>\n")
            return

        board_name = user_info.get("current_board")
        if not board_name:
            send_link_reply(packet.link, "You are not in any board. Use BOARD <board> first.\n")
            return

        boards_mgr.post_message(board_name, user_display_name, post_text)
        reply = f"Posted to board '{board_name}': {post_text}\n"
        send_link_reply(packet.link, reply)

    elif cmd in ["l", "list"]:
        board_name = remainder.strip()
        if board_name:
            handle_list_board(packet, board_name)
        else:
            cur_board = user_info.get("current_board")
            if not cur_board:
                send_link_reply(packet.link, "You are not in any board. Use BOARD <board> first.\n")
            else:
                handle_list_board(packet, cur_board)

    elif cmd in ["cb", "createboard"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return
        
        user_info = authorized_users.get(identity_hash_hex, {})
        if not user_info.get("is_admin", False):
            send_link_reply(packet.link, "ERROR: Only admins can create boards.\n")
            return

        board_name = remainder.strip()
        if not board_name:
            send_link_reply(packet.link, "Usage: CREATEBOARD <board_name>\n")
            return
        
        if not is_valid_board_name(board_name):
            send_link_reply(packet.link, "ERROR: Invalid board name. Must be alphanumeric and 3-20 characters long.\n")
        return

        boards_mgr.create_board(board_name)
        send_link_reply(packet.link, f"Board '{board_name}' is ready.\n")

    elif cmd in ["db", "deleteboard"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return
        
        user_info = authorized_users.get(identity_hash_hex, {})
        if not user_info.get("is_admin", False):
            send_link_reply(packet.link, "ERROR: Only admins can delete boards.\n")
            return

        board_name = remainder.strip()
        if not board_name:
            send_link_reply(packet.link, "Usage: DELETEBOARD <board_name>\n")
            return

        success = boards_mgr.delete_board(board_name)
        if success:
            reply = f"Board '{board_name}' has been deleted.\n"
        else:
            reply = f"Board '{board_name}' does not exist.\n"
        send_link_reply(packet.link, reply)

    elif cmd in ["a", "admin"]:
        if not is_authorized:
            send_link_reply(packet.link, "UNAUTHORIZED\n")
            return

        user_info = authorized_users.get(identity_hash_hex, {})
        if not user_info.get("is_admin", False):
            send_link_reply(packet.link, "ERROR: Only admins can assign admin rights.\n")
            return

        target_hash = remainder.strip()
        if not target_hash:
            send_link_reply(packet.link, "Usage: ADMIN <user_hash>\n")
            return

        if target_hash not in authorized_users:
            send_link_reply(packet.link, "ERROR: User does not exist.\n")
            return

        authorized_users[target_hash]["is_admin"] = True
        send_link_reply(packet.link, f"User {get_user_display(target_hash)} has been granted admin rights.\n")

        if auth_file_path:
            save_authorized_users(auth_file_path, authorized_users)

    else:
        send_link_reply(packet.link, "UNKNOWN COMMAND\n")

def is_valid_board_name(board_name):
    """
    Validates the board name.
    For example, board names must be alphanumeric and between 3-20 characters.
    """
    return board_name.isalnum() and 3 <= len(board_name) <= 20

def handle_join_board(packet, user_hash_hex, board_name):
    user_info = authorized_users[user_hash_hex]
    current = user_info.get("current_board")

    if current == board_name:
        reply = f"You are already in board '{board_name}'\n"
    else:
        #boards_mgr.create_board(board_name)
        user_info["current_board"] = board_name
        reply = f"You have joined board '{board_name}'\n"

    send_link_reply(packet.link, reply)

def handle_list_boards(packet):
    names = boards_mgr.list_boards()
    if not names:
        reply = "No boards exist.\n"
    else:
        reply = "All Boards:\n" + "\n".join(names) + "\n"
    send_resource_reply(packet.link, reply)

def handle_list_board(packet, board_name):
    posts = boards_mgr.list_messages(board_name)
    if not posts:
        reply = f"No messages on board '{board_name}'\n"
    else:
        lines = []
        for m in posts:
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["timestamp"]))
            lines.append(f"[{t_str} {m['author']}] {m['content']}")
        reply = "\n".join(lines) + "\n"
    send_resource_reply(packet.link, reply)

def send_link_reply(link, text):
    """
    Sends a reply to the client as a Packet.
    """
    data = text.encode("utf-8")
    RNS.Packet(link, data).send()

def send_resource_reply(link, text):
    """
    Instead of sending a normal packet, we create an RNS.Resource.
    This allows arbitrarily large 'text' to be transferred reliably.
    The client must be ready to accept resources.
    """
    data = text.encode("utf-8")
    resource = RNS.Resource(data, link)

auth_file_path = None

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="RetiBBS Server")
        parser.add_argument(
            "--config",
            action="store",
            default=None,
            help="Path to alternative Reticulum config directory",
            type=str
        )
        parser.add_argument(
            "--identity-file",
            action="store",
            default="server_identity.pem",
            help="Path to store or load the server identity (private key)",
            type=str
        )
        parser.add_argument(
            "--auth-file",
            action="store",
            default="authorized.json",
            help="Path to store or load authorized user data",
            type=str
        )
        args = parser.parse_args()

        auth_file_path = args.auth_file

        server_setup(args.config, args.identity_file, args.auth_file)

    except KeyboardInterrupt:
        print("")
        exit()
