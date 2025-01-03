import RNS

class ReplyHandler:
    def __init__(self):
        pass

    @staticmethod
    def send_link_reply(link, text):
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
        try:
            data = text.encode("utf-8")
            resource = RNS.Resource(data, link)
            RNS.log(f"[ReplyHandler] Sent resource reply (length={len(data)} bytes)", RNS.LOG_DEBUG)
        except Exception as e:
            RNS.log(f"[ReplyHandler] Error sending resource reply: {e}", RNS.LOG_ERROR)