Twitcheroo, a Python client library for using the Twitch API.

# HOW-TO
import os
from oauth import ClientCredentials
from client import Twitch


CLIENT_ID = "XXXXXXXXX"
CLIENT_SECRET = "XXXXXXXXX"
scope = []

auth = ClientCredentials(CLIENT_ID, CLIENT_SECRET, scope=scope)
twitch_session = Twitch(auth, max_retries=3, timeout=5.0)
twitch_session.get_extension_transactions("1234")



