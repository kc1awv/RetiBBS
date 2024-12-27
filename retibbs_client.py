#!/usr/bin/env python3
import argparse
import os
import sys
import time
import RNS

APP_NAME = "retibbs"
SERVICE_NAME = "bbs"

server_link = None
client_identity = None

def load_or_create_identity(identity_path):
    """
    Load a persistent Identity from disk. If it doesn't exist,
    create a new Identity, and save it to 'identity_path'.
    """
    if os.path.isfile(identity_path):
        identity = RNS.Identity.from_file(identity_path)
        RNS.log(f"[CLIENT] Loaded Identity from {identity_path}")
    else:
        identity = RNS.Identity()
        identity.to_file(identity_path)
        RNS.log(f"[CLIENT] Created new Identity and saved to {identity_path}")
    return identity

def client_setup(server_hexhash, configpath, identity_file):
    """
    Connects to the BBS server (by its hash), establishes a link,
    identifies to the server, and enters a command loop.
    """
    global client_identity

    reticulum = RNS.Reticulum(configpath)
    client_identity = load_or_create_identity(identity_file)
    RNS.log("[CLIENT] Using Identity: " + str(client_identity))
    
    try:
        server_addr = bytes.fromhex(server_hexhash)
    except ValueError:
        RNS.log("[CLIENT] Invalid server hexhash!")
        sys.exit(1)

    if not RNS.Transport.has_path(server_addr):
        RNS.log("[CLIENT] Path to server unknown, requesting path and waiting for announce...")
        RNS.Transport.request_path(server_addr)
        # Wait for the network to discover a path
        timeout_t0 = time.time()
        while not RNS.Transport.has_path(server_addr):
            if time.time() - timeout_t0 > 15:
                RNS.log("[CLIENT] Timed out waiting for path!")
                sys.exit(1)
            time.sleep(0.1)

    server_identity = RNS.Identity.recall(server_addr)
    if not server_identity:
        RNS.log("[CLIENT] Could not recall server Identity!")
        sys.exit(1)

    server_destination = RNS.Destination(
        server_identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        APP_NAME,
        SERVICE_NAME
    )

    link = RNS.Link(server_destination)
    link.set_link_established_callback(link_established)
    link.set_link_closed_callback(link_closed)
    link.set_packet_callback(client_packet_received)

    # IMPORTANT: Accept resources from the server
    link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
    link.set_resource_started_callback(resource_started_callback)
    link.set_resource_concluded_callback(resource_concluded_callback)

    RNS.log("[CLIENT] Establishing link with server...")
    wait_for_link(link)

def wait_for_link(link):
    """
    Poll until link is ACTIVE (established) or CLOSED (failed).
    """
    t0 = time.time()
    while link.status not in [RNS.Link.ACTIVE, RNS.Link.CLOSED]:
        if time.time() - t0 > 10:
            RNS.log("[CLIENT] Timeout waiting for link to establish.")
            link.teardown()
            sys.exit(1)
        time.sleep(0.1)

    if link.status == RNS.Link.ACTIVE:
        RNS.log("[CLIENT] Link is ACTIVE. Now identifying to server...")
        link.identify(client_identity)
    
        # Enter a loop that keeps the process alive
        client_loop()
    else:
        RNS.log("[CLIENT] Link could not be established (status=CLOSED).")
        sys.exit(1)

def client_loop():
    global server_link
    RNS.log("[CLIENT] Enter commands.")
    RNS.log("HELLO")
    RNS.log("    - Checks Authorization")
    RNS.log("NAME: <name>")
    RNS.log("    - Sets your display name")
    RNS.log("POST: <msg>")
    RNS.log("    - Posts a message to the board")
    RNS.log("LIST")
    RNS.log("    - Lists all messages on the server\r\n")
    RNS.log("quit with 'q', 'quit', 'QUIT', 'e', 'exit' or 'EXIT'.")

    while True:
        try:
            user_input = input("> ")
            if not user_input:
                continue

            if user_input.lower() in ["q", "quit", "QUIT", "e", "exit", "EXIT"]:
                RNS.log("[CLIENT] Closing link and exiting.")
                if server_link is not None:
                    server_link.teardown()
                RNS.Reticulum.exit_handler()
                time.sleep(1)
                os._exit(0)

            # Send data
            data = user_input.encode("utf-8")
            if len(data) <= RNS.Link.MDU:
                RNS.Packet(server_link, data).send()
            else:
                RNS.log(
                    f"[CLIENT] Data size {len(data)} exceeds MDU of {RNS.Link.MDU} bytes!",
                    RNS.LOG_ERROR
                )

        except KeyboardInterrupt:
            RNS.log("[CLIENT] KeyboardInterrupt -> Exiting.")
            if server_link is not None:
                server_link.teardown()
            sys.exit(0)
        except Exception as e:
            RNS.log("[CLIENT] Error while sending data: " + str(e))
            if server_link is not None:
                server_link.teardown()
            sys.exit(1)

def client_packet_received(message_bytes, packet):
    """
    Callback when data arrives from the server over the link.
    """
    text = message_bytes.decode("utf-8", "ignore")
    RNS.log("[CLIENT] Server says:\r\n" + text)

def resource_started_callback(resource):
    """
    Optional: Called when the server begins sending a resource.
    You could display a 'downloading...' message or track progress.
    """
    pass

def resource_concluded_callback(resource):
    """
    Called when the resource is fully transferred.
    We decode the data and display it in the TUI.
    """
    if resource.data is not None:
        fileobj = resource.data
        fileobj.seek(0)
        data = fileobj.read()
        text = data.decode("utf-8", "ignore")
        RNS.log("[SERVER-RESOURCE]\n" + text)
    else:
        RNS.log("[SERVER-RESOURCE] Transfer concluded, but no data received!")

def link_established(link):
    """
    Called when our link is fully established (before we identify).
    """
    RNS.log("[CLIENT] link_established callback, link is ready.")
    global server_link
    server_link = link

def link_closed(link):
    """
    Called if the server closes or link fails.
    """
    RNS.log("[CLIENT] Link was closed or lost. Exiting.")
    RNS.Reticulum.exit_handler()
    time.sleep(1)
    os._exit(0)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="RetiBBS Client")
        parser.add_argument(
            "--config",
            action="store",
            default=None,
            help="Path to alternative Reticulum config directory",
            type=str
        )
        parser.add_argument(
            "--server",
            action="store",
            default=None,
            required=True,
            help="Server hexhash to connect (e.g. e7a1f4d35b2a...)",
            type=str
        )
        parser.add_argument(
            "--identity-file",
            action="store",
            default="client_identity.pem",
            help="Path to store or load the client identity",
            type=str
        )

        args = parser.parse_args()
        client_setup(args.server, args.config, args.identity_file)

    except KeyboardInterrupt:
        print("")
        exit()
