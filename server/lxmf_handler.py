import time
import asyncio

import RNS
import LXMF

class LXMFHandler:
    def __init__(self, storage_path, identity, display_name):
        """
        Initialize the LXMFHandler.
        :param storage_path: Path to store Reticulum and LXMF data.
        :param logger: Optional logging function.
        """
        self.storage_path = storage_path
        self.router = LXMF.LXMRouter(storagepath=storage_path)
        if not self.router:
            RNS.log("Failed to initialize LXMF router.", RNS.LOG_ERROR)
            return
        self.identity = identity
        self.source = self.router.register_delivery_identity(
            self.identity,
            display_name=display_name,
            stamp_cost=8
        )
        self.router.announce(self.source.hash)
        RNS.log(f"LXMF source announced with hash: {self.source.hash.hex()}", RNS.LOG_DEBUG)
        self.message_queue = asyncio.Queue()

    def set_delivery_callback(self, callback):
        """
        Set the callback for delivery notifications.
        :param callback: Function to call when a message is delivered.
        """
        self.router.register_delivery_callback(callback)

    def request_path(self, recipient_hash):
        """
        Request a Reticulum path for a recipient and wait for availability.
        :param recipient_hash: Hexadecimal hash of the recipient.
        """
        recipient_bytes = bytes.fromhex(recipient_hash)
        if not RNS.Transport.has_path(recipient_bytes):
            RNS.log(f"Requesting path to recipient {recipient_hash}...", RNS.LOG_DEBUG)
            RNS.Transport.request_path(recipient_bytes)
            timeout = time.time() + 30
            while not RNS.Transport.has_path(recipient_bytes):
                if time.time() > timeout:
                    RNS.log(f"Failed to get path to recipient {recipient_hash}.", RNS.LOG_ERROR)
                    return
                time.sleep(0.1)
            RNS.log(f"Path to recipient {recipient_hash} resolved.", RNS.LOG_DEBUG)

    def send_message(self, recipient_hash, title, body):
        """
        Send an LXMF message.
        :param recipient_hash: Hexadecimal hash of the recipient.
        :param title: Message title.
        :param body: Message body.
        """
        try:
            recipient_bytes = bytes.fromhex(recipient_hash)
            self.request_path(recipient_hash)

            recipient_identity = RNS.Identity.recall(recipient_bytes)
            if not recipient_identity:
                RNS.log("Failed to recall recipient identity.", RNS.LOG_ERROR)
                return
            RNS.log(f"Recalled recipient identity: {recipient_identity.hash.hex()}", RNS.LOG_DEBUG)

            destination = RNS.Destination(
                recipient_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery"
            )

            message = LXMF.LXMessage(
                destination,
                self.source,
                body,
                title,
                desired_method=LXMF.LXMessage.DIRECT,
                include_ticket=True
            )

            self.router.handle_outbound(message)
            RNS.log(f"Message sent to {recipient_hash}: {title}", RNS.LOG_DEBUG)

        except Exception as e:
            RNS.log(f"Error sending message: {e}", RNS.LOG_ERROR)

    async def monitor_and_send(self):
        """
        Monitor the message queue and send messages as they arrive.
        """
        while True:
            event = await self.message_queue.get()
            self.send_message(event['recipient'], event['title'], event['body'])
            self.message_queue.task_done()

    async def enqueue_message(self, recipient, title, body):
        """
        Add a message to the queue for sending.
        :param recipient: Recipient's LXMF address in hexadecimal.
        :param title: Message title.
        :param body: Message body.
        """
        await self.message_queue.put({
            "recipient": recipient,
            "title": title,
            "body": body,
        })
        RNS.log(f"Message enqueued for {recipient}: {title}", RNS.LOG_DEBUG)
        try:
            self.send_message(recipient, title, body)
        except Exception as e:
            RNS.log(f"Error sending message to {recipient}. Retrying in 10 seconds: {e}", RNS.LOG_ERROR)
            await asyncio.sleep(10)
            await self.enqueue_message(recipient, title, body)