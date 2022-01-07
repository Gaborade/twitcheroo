from authlib.integrations.requests_client import OAuth2Session
from authlib.common.urls import add_params_to_uri
from constants import SUPPORTED_SCOPES, APIv5_SCOPES
import requests
import warnings

from exceptions import TwitchError


class ClientCredentials:
    TWITCH_OAUTH_TOKEN_URL: str = "https://id.twitch.tv/oauth2/token"
    TWITCH_API_BASE_URL: str = "https://api.twitch.tv"

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 scope: str = None,
                 grant_type: str = "client_credentials"
                ):
        
        if not isinstance(client_id, str):
            raise TypeError("Client_id should be a string")
        if not isinstance(client_secret, str):
            raise TypeError("Client_secret should be a string")
        if scope:
            if not isinstance(scope, str):
                raise TypeError("Scope should be a string")
            if len(scope.split(" ")) > 1:
                scopes_list = scope.split(" ")
                for element in scopes_list:
                    if element not in SUPPORTED_SCOPES or APIv5_SCOPES:
                        raise ValueError("Scope provided not supported by Twitch")
                    elif element in APIv5_SCOPES:
                        # warnings show only once in a module
                        warnings.warn("TWITCH APIv5 is legacy API, it is advisable to switch to new api version")
                # then use regex to figure out if the scopes are space separated
                # then if scope string doesn't match regex raise a ValueError
                raise ValueError("Scope should be separated by space( )")

        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__scope = scope
        self.__grant_type = grant_type
        self.__access_token = None
        if self.__access_token is None:
            self.__session = OAuth2Session(self.__client_id, self.__client_secret)
        self.__session = OAuth2Session(
                            self.__client_id,
                            self.__client_secret,
                            token = self.__access_token
                             )                       
    
    @property
    def client_id(self):
        return self.__client_id

    @client_id.setter
    def client_id(self, new_client_id: str):
        self.__client_id = new_client_id

    @property
    def client_secret(self):
        return self.__client_secret

    @client_secret.setter
    def client_secret(self, new_client_secret: str):
        self.__client_secret = new_client_secret

    def _generate_twitch_token_url(self, method: str =  "POST"):

        """
           Twitch requires adding the cilent_id and client_url when sending POST request to obtain access tokens
           during the usage of the client credentials OAuth flow
        """
        
        if self.__scope:
            twitch_token_url= add_params_to_uri(self.TWITCH_OAUTH_TOKEN_URL, [
                ("client_id", self.__client_id),
                ("client_secret", self.__client_secret),
                ("grant_type", self.__grant_type),
                ("scope", self.__scope)
            ])
        else:    
            twitch_token_url = add_params_to_uri(self.TWITCH_OAUTH_TOKEN_URL, [
                ("client_id", self.__client_id),
                ("client_secret", self.__client_secret),
                ("grant_type", self.__grant_type)
            ])

        return twitch_token_url
        
    def get_access_token(self):
        twitch_token_url = self._generate_twitch_token_url()
        self.__access_token = self.__session.fetch_token(twitch_credentials_url)
        return self.__access_token

    def set_access_token(self, new_access_token: dict):
        if not isinstance(new_access_token, dict):
            raise TypeError("Access token should be a dict type")
        self.__access_token = new_access_token


    # when validating twitch requests, i should always make a request to "http://id.twitch.tv/oauth2/validate"
    # with access token in the header, the response will include the status of the token and a successful response will
    # show that the access token is valid

    # for my app i need app_access_tokens expire after 60 days so i should check that the app access token is valid
    # by making a request to aforementioned validate endpoint, then if token has expired i generate a new one
    # also note, app_access_tokens are meant for server-to-server api requests and shouldn't be used in client code
    # app access token is also a bearer token

    def validate_request(self):
        twitch_validate_request_url = self.TWITCH_OAUTH_TOKEN_URL.replace("token", "validate", 1)

        try:
            # does it come with status_codes
            response = self.__session.get(twitch_validate_url)
            response.raise_for_status()
        except Exception as e:
            raise TwitchError()
        else:
            return

        
    









       



                                                                                                                         
