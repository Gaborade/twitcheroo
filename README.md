Twitcheroo, a Python client library for using the Twitch API.


### FEATURES

- [x] Timeouts
- [x] Retries and Backoffs
- [x] Support for all Twitch API endpoints
- [ ] Pagination support
- [ ] Support for PubSub

# HOW-TO
   ```py
   from twitcheroo import ClientCredentials, Twitch   

   CLIENT_ID = "turtles"
   CLIENT_SECRET = "allthewaydown"
   scope = ["analytics:read:games"]
   auth = ClientCredentials(CLIENT_ID, CLIENT_SECRET, scope=scope)
   twitch_session = Twitch(auth, max_retries=4, timeout=10.0)
   print(twitch_session.get_extension_transactions("1234"))

   ```
   For more samples, refer to examples directory(available in due course)
