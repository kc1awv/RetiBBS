import RNS

class ReplyHandler:
    def __init__(self):
        pass

    @staticmethod
    def send_link_reply(link, text):
        """
        Send a reply to a link.
        :param link: The link to reply to.
        :param text: The text to send.
        """
        try:
            data = text.encode("utf-8")
            if link.destination.hash == RNS.Transport.identity.hash:
                RNS.log(f"[ERROR] Attempted to send packet to self. Destination hash: {RNS.prettyhexrep(link.destination.hash)}", RNS.LOG_ERROR)
                return
            packet = RNS.Packet(link, data)
            packet.send()
            RNS.log(f"[ReplyHandler] Sent link reply: {text}", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending link reply: {e}", RNS.LOG_ERROR)

    @staticmethod
    def send_resource_reply(link, text):
        """
        Send a resource reply to a link.
        :param link: The link to reply to.
        :param text: The text to send.
        """
        try:
            data = text.encode("utf-8")
            resource = RNS.Resource(data, link)
            RNS.log(f"[ReplyHandler] Sent resource reply (length={len(data)} bytes)", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending resource reply: {e}", RNS.LOG_ERROR)
    
    @staticmethod
    def send_clear_screen(link):
        """
        Send a clear screen command to a link.
        :param link: The link to send the command to.
        """
        try:
            control_packet = b"CTRL CLS"
            packet = RNS.Packet(link, control_packet)
            packet.send()
            RNS.log(f"[ReplyHandler] Sent clear screen", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending clear screen: {e}", RNS.LOG_ERROR)

    @staticmethod
    def send_area_update(link, area):
        """
        Send an area update command to a link.
        :param link: The link to send the command to.
        :param area: The area to switch to.
        """
        try:
            control_packet = f"CTRL AREA {area}".encode("utf-8")
            packet = RNS.Packet(link, control_packet)
            packet.send()
            RNS.log(f"[ReplyHandler] Sent area update: {area}", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending area update: {e}", RNS.LOG_ERROR)

    @staticmethod
    def send_board_update(link, board_name):
        """
        Send a board update command to a link.
        :param link: The link to send the command to.
        :param board_name: The board to switch to.
        """
        try:
            control_packet = f"CTRL BOARD {board_name}".encode("utf-8")
            packet = RNS.Packet(link, control_packet)
            packet.send()
            RNS.log(f"[ReplyHandler] Sent board update: {board_name}", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending board update: {e}", RNS.LOG_ERROR)