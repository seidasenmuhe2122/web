import os
from django.core.management.base import BaseCommand
class Command(BaseCommand):
    help = 'Create a Telethon StringSession locally.'
    def handle(self, *args, **opts):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        api_id = int(os.environ['TELEGRAM_API_ID']); api_hash = os.environ['TELEGRAM_API_HASH']
        with TelegramClient(StringSession(), api_id, api_hash) as client:
            self.stdout.write(client.session.save())
