import asyncio

from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Label

class ServerDetailScreen(ModalScreen):
    def __init__(self, server_name, destination_hash, timestamp, on_connect, saved_in_address_book):
        super().__init__()
        self.server_name = server_name
        self.destination_hash = destination_hash
        self.timestamp = timestamp
        self.on_connect = on_connect
        self.saved_in_address_book = saved_in_address_book

    def compose(self):
        yield Grid(
            Label(
                f"Server Name: {self.server_name}\nDestination Hash: {self.destination_hash}\nLast Heard: {self.timestamp}",
                id="server_details"
            ),
            Button("Connect", id="connect", variant="success", classes="button"),
            Button(
                "Remove from Address Book" if self.saved_in_address_book else "Save to Address Book",
                id="toggle_address_book",
                variant="primary",
                classes="button",
            ),
            Button("Close", id="close", variant="default", classes="button"),
            id="server_details_dialog",
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "connect":
            asyncio.create_task(self.on_connect(self.destination_hash))
            self.app.pop_screen()
        elif event.button.id == "toggle_address_book":
            self.app.pop_screen()
            self.app.toggle_address_book(self.destination_hash, self.saved_in_address_book)
        elif event.button.id == "close":
            self.app.pop_screen()


class HelpScreen(ModalScreen):
    def compose(self):
        help_text = (
            "Welcome to the RetiBBS Client!\n\n"
            "Available Key Bindings:\n"
            "  q      - Quit the application\n"
            "  ?      - Show this help screen\n\n"
            "Use the arrow keys to navigate the interface.\n"
        )
        yield Grid(
            Label(help_text, id="help_text"),
            Button("Close", id="close_help", variant="default", classes="button"),
            id="help_dialog",
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close_help":
            self.app.pop_screen()