from authlib.integrations.requests_client import OAuth2Session
from authlib.common.urls import add_params_to_uri
from constants import SUPPORTED_SCOPES, APIv5_SCOPES
from typing import List, Optional
import requests
import warnings
import os
import time
import pickle
import time

from exceptions import TwitchAuthException


class ClientCredentials:
    TWITCH_OAUTH_TOKEN_URL: str = "https://id.twitch.tv/oauth2/token"
    TWITCH_API_BASE_URL: str = "https://api.twitch.tv"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = None,
        grant_type: str = "client_credentials",
    ):

        assert isinstance(client_id, str), "Client id should be a string"
        self.__client_id = client_id
        assert isinstance(client_secret, str), "Client secret should be a string"
        self.__client_secret = client_secret

        if scopes:
            assert isinstance(scopes, list), "Scope should be a list data type"
            self._parse_scope_for_errors(scopes)
            self.scopes = " ".join(scope for scope in scopes)
        else:
            # or self.scopes = "" so no errors will occur when client.py checks for scopes
            # if scope is None, checking for scopes will produce errors since None is
            # not an iterable
            self.scopes = None

        self.grant_type = grant_type
        self.access_token = None
        if self.scopes is not None:
            self.session = OAuth2Session(self.__client_id, self.__client_secret)
        self.session = OAuth2Session(
            self.__client_id, self.__client_secret, self.scopes
        )
        self.access_token_file = None
        self.next_validate_token_time = 0

    @staticmethod
    def _parse_scope_for_errors(twitch_scopes):
        if len(twitch_scopes) == 1:
            if (
                twitch_scopes[0] not in SUPPORTED_SCOPES
                and twitch_scopes[0] not in APIv5_SCOPES
            ):
                raise ValueError(
                    f"Scope provided <{scopes[0]}> not supported by Twitch"
                )
            if twitch_scopes[0] in APIv5_SCOPES:
                warnings.warn(
                    f"""Scope provided <{twitch_scopes[0]}> is for Twitch legacy APIv5, 
                recommeneded to switch to new API version """
                )
            return
        else:
            scope_in_apiv5 = []
            for x in twitch_scopes:
                if x not in SUPPORTED_SCOPES and x not in APIv5_SCOPES:
                    raise ValueError(f"Scope provided <{x}> not supported by Twitch")
                if x in APIv5_SCOPES:
                    scope_in_apiv5.append(x)
            if scope_in_apiv5:
                warnings.warn(
                    f"""Scopes provided {scope_in_apiv5} are for Twitch legacy APIv5, recommended to switch to 
                    new API version """
                )
            return

    @property
    def client_id(self):
        return self.__client_id

    @client_id.setter
    def client_id(self, new_client_id: str):
        assert isinstance(new_client_id, str), "Client_id should be a string type"
        self.__client_id = new_client_id

    @property
    def client_secret(self):
        return self.__client_secret

    @client_secret.setter
    def client_secret(self, new_client_secret: str):
        assert isinstance(new_client_secret), "Client secret should be a string type"
        self.__client_secret = new_client_secret

    def __call__(self):
        if self.access_token is None:
            self.get_access_token()
        if not self.token_is_validated():
            self.get_access_token(check_cache=False)
        if self.is_token_expired():
            self.get_access_token(check_cache=False)
        return self.session

    def _generate_twitch_token_url(self):

        """
        Twitch requires adding the cilent_id and client_url when sending POST request to obtain access tokens
        during the usage of the client credentials OAuth flow
        """

        if self.scopes is not None:
            twitch_token_url = add_params_to_uri(
                self.TWITCH_OAUTH_TOKEN_URL,
                [
                    ("client_id", self.__client_id),
                    ("client_secret", self.__client_secret),
                    ("grant_type", self.grant_type),
                    ("scope", self.scopes),
                ],
            )
        else:
            twitch_token_url = add_params_to_uri(
                self.TWITCH_OAUTH_TOKEN_URL,
                [
                    ("client_id", self.__client_id),
                    ("client_secret", self.__client_secret),
                    ("grant_type", self.grant_type),
                ],
            )

        return twitch_token_url

    def get_access_token(self, check_cache=True):
        get_token_loop = True
        while get_token_loop:
            if check_cache and self.read_access_token() is not None:
                saved_access_token = self.read_access_token()
                # check pickle for corruption
                if not isinstance(saved_access_token, dict):
                    check_cache = False
                else:
                    self.access_token = saved_access_token
                    get_token_loop = False
            else:
                twitch_token_url = self._generate_token_url()
                self.access_token = self.session.fetch_token(twitch_token_url)
                self.save_access_token(self.access_token)
                get_token_loop = False
        if self.scopes is not None:
            self.session = OAuth2Session(
                self.__client_id,
                self.__client_secret,
                self.scopes,
                token=self.access_token,
            )
        else:
            self.session = OAuth2Session(
                self.__client_id, self.__client_secret, token=self.access_token
            )

    def set_access_token(self, new_access_token: dict):
        assert isinstance(new_access_token, dict), "Access token should be a dict type"
        self.access_token = new_access_token

    def is_token_validated(self):
        """
        Validate twitich access tokens with the https://id.twitch.tv/oauth2/validate endpoint.
        Validating tokens should be done on an hourly basis. A valid token request returns HTTP
        status code 200 upon success and HTTP status code 401 when token is no longer valid
        """

        twitch_validate_token_url = self.TWITCH_OAUTH_TOKEN_URL.replace(
            "token", "validate"
        )
        if time.time() > self.next_validate_token_time:
            response = self.session.get(twitch_validate_token_url)
            if response.status_code == 200:
                # the next validation will be in the next hour ie 3600 seconds later
                self.next_validate_token_time = time.time() + 3600
                return True
            elif response.status_code == 401:
                self.next_validate_token_time = 0
                return False
        else:
            return True

    def is_token_expired(self):
        "App access tokens expire after 60 days"
        if time.time() > self.access_token["expires_at"]:
            return True
        return False

    def save_access_token(self):
        if self.access_token is None:
            return
        with open(".client_credentials.pickle", "wb") as client_credentials_file:
            pickle.dump(
                self.access_token, client_credentials_file, pickle.HIGHEST_PRIORITY
            )

    def read_access_token_from_file(self):
        try:
            with open(".client_credentials.pickle", "rb") as client_credentials_file:
                data = pickle.load(client_credentials_file)
        except FileNotFoundError:
            return None
        else:
            # if pickle is corrupted, return a string instead of a dict
            # so i can run a typecheck in get_access_token method
            return data


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # user = ClientCredentials(
    #  os.environ["CLIENT_ID"], os.environ["CLIENT_SECRET"], scope="bits:read"
    # )
    sec_user = ClientCredentials(
        os.environ["CLIENT_ID"],
        os.environ["CLIENT_SECRET"],
        scope=["chat:read", "chat:edit"],
    )
    sec_user
    # print(user.scope)
    # print(user.get_access_token())
    # print(user.is_token_validated())
