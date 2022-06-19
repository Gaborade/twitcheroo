Twitcheroo, a Python client library for using the Twitch API.


### FEATURES

- [x] Timeouts
- [x] Retries and Backoffs
- [ ] Pagination support

# HOW-TO
   ```py
   from twitcheroo import ClientCredentials, Twitch   

   CLIENT_ID = "turtles"
   CLIENT_SECRET = "allthewaydown"
   auth = ClientCredentials(CLIENT_ID, CLIENT_SECRET)
   twitch_session = Twitch(auth, max_retries=4, timeout=10.0)
   print(twitch_session.get_extension_transactions("1234"))

   ```
   For more samples, refer to examples directory
