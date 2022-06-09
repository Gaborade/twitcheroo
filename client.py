import sys
import time
import requests
import random
from tenacity import retry
from typing import Optional, Dict, Any, Union, List
from oauth import ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow
from authlib.common.urls import add_params_to_uri
from exceptions import (
    TwitchAuthException,
    InvalidRequestException,
    BadRequestError,
    ScopeError,
    TwitchInternalServerError,
    TooManyRequestsError,
    UnAuthorizedError,
    ForbiddenError,
    NetworkConnectionError,
)


SECONDS = int
http_errors = {
    400: BadRequestError,
    401: UnAuthorizedError,
    403: ForbiddenError,
    429: TooManyRequestsError,
}


class Twitch:
    TWITCH_API_BASE_URL: str = "https://api.twitch.tv/helix"
    AUTH_OBJECTS: List[Any] = [
        ClientCredentials,
        AuthorizationCodeFlow,
        OIDCAuthorizationCodeFlow,
    ]

    def __init__(
        self,
        auth: Union[
            ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow
        ],
        max_retries: int = 3,
        timeout: float = 10.0,
    ):
        if not any(
            isinstance(auth, auth_object) for auth_object in Twitch.AUTH_OBJECTS
        ):
            raise TwitchAuthException(
                f"""Authentication class <{auth.__class__.__name__}> not supported by API.
                 Use ClientCredentials, AuthorizationCodeFlow or OIDCAuthorizationCodeFlow 
                authentication classes"""
            )

        self.auth = auth
        self.twitch_session, self.twitch_scope = self.auth()
        self.max_retries = int(max_retries)
        self.timeout = float(timeout)

    @staticmethod
    def _apply_exponential_backoff(backoff: SECONDS) -> None:
        # random_milliseconds needed to add random jitter
        # 1000 milliseconds make a second
        # need to convert milliseconds to seconds for time.sleep
        random_milliseconds = random.randrange(0, 1000) / 1000
        backoff += random_milliseconds
        time.sleep(backoff)

    def twitch_request(
        self,
        method: str,
        endpoint: str,
        request_body=None,
        jwt_required=False,
        oauth_token_required=False,
        app_access_token_required=False,
        app_or_oauth_token_required=False,
        pagination=False,
        **query_parameters,
    ):
        # reminder to always set one of these keyword parameters to True
        # for every Twitch endpoint method created.
        assert_msg = (
            "One of oauth_token_required, app_access_token_required or "
            "app_or_oauth_token_required kwargs should be set to True "
            "for any Twitch endpoint method created."
        )

        assert any(
            [
                oauth_token_required,
                app_access_token_required,
                app_or_oauth_token_required,
            ]
        ), assert_msg

        if app_access_token_required:
            if not isinstance(self.auth, ClientCredentials):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an app access token"
                )

        if oauth_token_required:
            if not isinstance(self.auth, AuthorizationCodeFlow):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an oauth token"
                )

        if app_or_oauth_token_required:
            if not isinstance(self.auth, ClientCredentials) and not isinstance(
                self.auth, AuthorizationCodeFlow
            ):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an app access token or oauth token"
                )

        if jwt_required:
            if not isinstance(self.auth, OIDCAuthorizationCodeFlow):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint requires a jwt token"
                )

        request_body = request_body if request_body is not None else {}
        query_parameters = query_parameters if query_parameters else {}

        if query_parameters:
            fragments = []
            for k, v in query_parameters.copy().items():
                if isinstance(v, list):
                    pop_list = query_parameters.pop(k)
                    fragments += [(k, element) for element in pop_list]
            build_url = [
                (key, value)
                for key, value in query_parameters.items()
                if value is not None
            ]
            build_url += fragments
            url = add_params_to_uri(self.TWITCH_API_BASE_URL + endpoint, build_url)
        else:
            url = self.TWITCH_API_BASE_URL + endpoint

        retries = self.max_retries
        delay_seconds = 1.2

        while retries >= 0:
            try:
                if request_body:
                    # request session needs to be closed so it doesn't hang
                    # hanging requests don't allow other retries to occur
                    # hence the context manager
                    with self.twitch_session as session:
                        response = session.request(
                            method, url, body=request_body, timeout=self.timeout
                        )
                else:
                    with self.twitch_session as session:
                        response = session.request(method, url, timeout=self.timeout)

                if response.status_code == 500:
                    raise TwitchInternalServerError

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                TwitchInternalServerError,
            ) as e:

                if retries != 0:
                    self._apply_exponential_backoff(delay_seconds)
                    # exponentially increase delay seconds
                    delay_seconds **= 2
                    retries -= 1

                elif retries == 0:
                    if isinstance(e, TwitchInternalServerError):
                        raise TwitchInternalServerError("status_code=500")

                    if isinstance(e, requests.exceptions.ConnectionError):
                        exc_msg = sys.exc_info()[1]
                        exc_msg = str(exc_msg).replace(
                            "retries", "retries={}".format(self.max_retries)
                        )
                        raise NetworkConnectionError(exc_msg)
                    raise e

            else:
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 204:
                    return response.status_code
                else:
                    global http_errors
                    if response.status_code in http_errors:
                        raise http_errors[response.status_code](response.json())

    def start_commercial(self, data):
        "Start a commerical on a specified channel"

        assert isinstance(data, dict), "data should be a dict type"

        required_scope = "channel:edit:commercial"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["broadcaster_id", "length"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items if key in required_params
        }
        return self.twitch_request(
            "post",
            "/channels/commercial",
            request_body=request_body,
            oauth_token_required=True,
        )

    def get_extension_analytics(
        self,
        after: str = None,
        ended_at: str = None,
        extension_id: str = None,
        first: int = 20,
        started_at: str = None,
        type: str = "overview_v2",
    ):
        """
        Gets a URL Extension that developers can use to download analytics
        reports (CSV files) for their extensions. The URL is valid for 5
        minutes. For detals about analytics and the fields returned, see
        the Insights & Analytics guide.
        """

        required_scope = "analytics:read:extensions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if started_at is not None or ended_at is not None:
            if not all([started_at, ended_at]):
                raise InvalidRequestException(
                    """
                    started_at and ended_at optional query parameters are
                    always used together.
                    """
                )

        return self.twitch_request(
            "get",
            "/analytics/extensions",
            oauth_token_required=True,
            after=after,
            ended_at=ended_at,
            extension_id=extension_id,
            first=first,
            started_at=started_at,
            type=type,
        )

    def get_game_analytics(
        self,
        after: str,
        ended_at: str = None,
        first: int = 20,
        game_id: str = None,
        started_at: str = None,
        type: str = "overview_v2",
    ):
        """
        Gets a URL that game developers can use to download analytics reports
        (CSV files) for their games. The URL is valid for 5 minutes.
        """

        required_scope = "analytics:read:games"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if started_at is not None or ended_at is not None:
            if not all([started_at, ended_at]):
                raise InvalidRequestException(
                    """
                    started_at and ended_at optional query parameters are
                    always used together
                    """
                )

        return self.twitch_request(
            "get",
            "/analytics/games",
            oauth_token_required=True,
            after=after,
            ended_at=ended_at,
            first=first,
            game_id=game_id,
            started_at=started_at,
            type=type,
        )

    def get_bits_leaderboard(
        self,
        count: int = None,
        period: str = None,
        started_at: str = None,
        user_id: str = None,
    ):
        """
        Gets a ranked list of Bits leaderboard information for an authorized
        broadcaster.
        """

        required_scope = "bits:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/bits/leaderboard",
            oauth_token_required=True,
            count=count,
            period=period,
            started_at=started_at,
            user_id=user_id,
        )

    def get_cheermotes(self, broadcaster_id: str):
        """
        Retrieves the list of available Cheermotes, animated emotes to which
        viewers can assign Bits, to cheer in chat. Cheermotes returned are
        available throughout Twitch, in all Bits-enabled channels.
        """

        return self.twitch_request(
            "get",
            "/bits/cheermotes",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def get_extension_transactions(
        self, extension_id: str, id: str = None, after: str = None, first: int = 20
    ):
        """
        Gets the list of Extension transactions for a given extension. This allows
        Extension back-end servers to fetch a list of transactions that have occurred
        for their Extension across all of Twitch.
        """

        return self.twitch_request(
            "get",
            "/extensions/transactions",
            app_access_token_required=True,
            extension_id=extension_id,
            id=id,
            after=after,
            first=first,
        )

    def get_channel_information(self, broadcaster_id: str):
        """Gets channel information for users."""

        return self.twitch_request(
            "get",
            "/channels",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def modify_channel_information(self, broadcaster_id: str, data):
        """Modifies channel information for users."""

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:broadcast"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        body_params = ["game_id", "broadcaster_language", "title", "delay"]
        request_body = {
            key: value for (key, value) in data.items() if key in body_params
        }
        return self.twitch_request(
            "patch",
            "/channels",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def get_channel_editors(self, broadcaster_id: str):
        """
        Gets a list of users who have editor permissions for a specific
        channel.
        """

        required_scope = "channel:read:editors"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/channel/editors",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def create_custom_rewards(self, broadcaster_id, data):
        "Creates a Custom Reward on a channel."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["title", "cost"]
        optional_params = [
            "prompt",
            "is_enabled",
            "background_color",
            "is_user_input_required",
            "is_max_per_stream_enabled",
            "max_per_stream",
            "is_max_per_user_per_stream_enabled",
            "max_per_user_per_stream",
            "is_global_cooldown_seconds",
            "global_cooldown_seconds",
            "should_redemptions_skip_request_queue",
        ]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "post",
            "/channel_points/custom_rewards",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def delete_custom_reward(self, broadcaster_id: str, id: str):
        "Deletes a Custom Reward on a channel."

        required_scope = "channel:manage:redemptions"
        if required_scope not in required_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "delete",
            "/channel_points/custom_rewards",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
        )

    def get_custom_reward(
        self,
        broadcaster_id: str,
        id: Optional[str] = None,
        only_manageable_rewards: bool = False,
    ):
        """
        Returns a list of Custom Reward objects for the Custom Reward objects
        for the Custom Rewards on a channel.
        """

        required_scope = "channel:read:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        self.twitch_request(
            "get",
            "/channel_points/custom_rewards",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
            only_manageable_rewards=only_manageable_rewards,
        )

    def get_custom_reward_redemption(
        self,
        broadcaster_id: str,
        reward_id: str,
        id=None,
        status: Optional[str] = None,
        sort: str = "OLDEST",
        after: Optional[str] = None,
        first: int = 20,
    ):
        """
        Returns Custom Reward Redemption objects for a Custom Reward
        on a channel that was created by the same client_id.
        """

        required_scope = "channel:read:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/channel_points/custom_rewards/redemptions",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            reward_id=reward_id,
            id=id,
            status=status,
            sort=sort,
            after=after,
            first=first,
        )

    def update_custom_reward(self, broadcaster_id: str, id: str, data):
        "Updates a Custom Reward created on a channel."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        optional_params = [
            "title",
            "prompt",
            "cost",
            "background_color",
            "is_enabled",
            "is_user_input_required",
            "is_user_input_required",
            "is_max_per_stream_enabled",
            "max_per_stream",
            "is_max_per_user_per_stream_enabled",
            "max_per_user_per_stream",
            "is_global_cooldown_enabled",
            "global_cooldown_seconds",
            "is_paused",
            "should_redemptions_skip_request_queue",
        ]
        request_body = {
            key: value for (key, value) in data.items() if key in optional_params
        }
        return self.twitch_request(
            "patch",
            "channel_points/custom_rewards",
            request_body=request_body,
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
        )

    def update_redemption_status(
        self, id: str, broadcaster_id: str, reward_id: str, data
    ):
        """
        Updates the status of Custom Reward Redemption objects on a
        channel that are in the UNFULFILLED status.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["status"]
        if required_params[0] not in data.keys():
            raise InvalidRequestException(
                f"{required_params[0]} is a required body parameter"
            )

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "patch",
            "/channel_points/custom_rewards/redemptions",
            oauth_token_required=True,
            request_body=request_body,
            id=id,
            broadcaster_id=broadcaster_id,
            reward_id=reward_id,
        )

    def get_channel_emotes(self, broadcaster_id: str):
        """
        Gets all emotes that the specified Twitch channel created. For example,
        subscriber emotes, follower emotes, and Bits tier emotes.
        """

        return self.twitch_request(
            "get",
            "/chat/emotes",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def get_global_emotes(self):
        """
        Gets all global emotes. Global emotes are Twitch-specific emoticons
        that every user can use in Twitch chat.
        """

        return self.twitch_request(
            "get", "/chat/emotes/global", app_or_oauth_token_required=True
        )

    def get_emote_sets(self, emote_set_id: str):
        "Get emotes for one or more specified emote sets."

        return self.twitch_request(
            "get",
            "/chat/emotes/set",
            app_or_oauth_token_required=True,
            emote_set_id=emote_set_id,
        )

    def get_channel_chat_badges(self, broadcaster_id: str):
        """
        Gets a list of custom chat badges that can be used in chat for the
        specified channel. This includes subscriber badges and Bit badges.
        """

        return self.twitch_request(
            "get",
            "/chat/badges",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def get_global_chat_badges(self):
        """
        Get a list of chat badges that can be used in any
        chat for any channel.
        """

        return self.twitch_request(
            "get", "/chat/badges/global", app_or_oauth_token_required=True
        )

    def get_chat_settings(
        self, broadcaster_id: str, moderator_id: Optional[str] = None
    ):
        "Gets the broadcaster's chat settings."

        if moderator_id is not None:
            required_scope = "moderator:read:chat_settings"
            if required_scope not in self.twitch_scope:
                raise ScopeError(
                    f"[{required_scope}] scope required if moderator_id is provided"
                )

        return self.twitch_request(
            "get",
            "/chat/settings",
            app_access_token_required=True,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def update_chat_settings(self, broadcaster_id: str, moderator_id: str, data):
        "Updates the broadcaster's chat settings."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "moderator:manage:chat_settings"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        params = [
            "emote_mode",
            "follower_mode",
            "follower_mode_duration",
            "non_moderator_chat_delay",
            "non_moderator_chat_delay_duration",
            "slow_mode",
            "slow_mode_wait_time",
            "subscriber_mode",
            "unique_chat_mode",
        ]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "patch",
            "/chat/settings",
            request_body=request_body,
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def create_clip(self, broadcaster_id: str, has_delay: bool = False):
        """
        Creates a clip programmatically. This returns both an ID
        and an edit URL for the new clip.
        """

        required_scope = "clips:edit"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "post",
            "/clips",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            has_delay=has_delay,
        )

    def get_clips(
        self,
        broadcaster_id: str,
        game_id: str,
        id: str,
        after: Optional[str] = None,
        before: Optional[str] = None,
        ended_at: Optional[str] = None,
        first: int = 20,
        started_at: Optional[str] = None,
    ):
        """
        Gets clip information by clip ID (one or more), broadcaster ID (one only),
        or game ID (one only).
        """

        return self.twitch_request(
            "get",
            "/clips",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            game_id=game_id,
            id=id,
            after=after,
            before=before,
            ended_at=ended_at,
            first=first,
            started_at=started_at,
        )

    def get_code_status(self, code: str, user_id: int):
        """
        Gets the status of one or more provided codes. This API requires that
        the caller is an authenticated Twitch user. The API is throttled to at
        least request per second per authenticated user.
        """

        return self.twitch_request(
            "get",
            "/entitlements/codes",
            app_access_token_required=True,
            code=code,
            user_id=user_id,
        )

    def get_drops_entitlements(
        self,
        id: str = None,
        user_id: str = None,
        game_id: str = None,
        fulfillment_status: str = None,
        after: str = None,
        first: int = 20,
    ):
        """
        Gets a list of entitlements for a given organization that have been
        granted to a game, user or both.
        """

        return self.twitch_request(
            "get",
            "/entitlements/drops",
            app_or_access_token_required=True,
            id=id,
            user_id=user_id,
            game_id=game_id,
            fulfillment_status=fulfillment_status,
            after=after,
            first=first,
        )

    def update_drops_entitlements(self, data):
        """
        Updates the fulfillment status on a set of Drops entitlements, specified
        by their entitlement IDs.
        """

        assert isinstance(data, dict), "data should be a dict type"
        params = ["entitlement_ids", "fulfillment_status"]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "patch",
            "entitlements/drops",
            app_or_oauth_token_required=True,
            request_body=request_body,
        )

    def redeem_code(self, code: str, user_id: int):
        "Redeems one or more redemption codes."

        return self.twitch_request(
            "post",
            "/entitlements/codes",
            app_access_token_required=True,
            code=code,
            user_id=user_id,
        )

    def get_extension_configuration_segment(
        self, broadcaster_id: str, extension_id: str, segment: str
    ):
        """
        Sets a single configuration segment of any type. The segment type is
        specified as a body parameter.
        NOTE: You can retrieve each segment a maximum of 20 times per
        minute. If you exceed the limit, the request returns HTTP status
        code 429. To determine when you may resume making requests, see
        the Ratelimit-Reset response header.
        """

        return self.twitch_request(
            "get",
            "/extensions/configurations",
            jwt_required=True,
            broadcaster_id=broadcaster_id,
            extension_id=extension_id,
            segment=segment,
        )

    def set_extension_configuration_segment(self, data):
        """
        Sets a single configuration segment of any type. The segment type
        is specified as a body parameter.
        Each segment is limited to 5 KB and can be set at most 20 times
        per minute. Updates to this data are not delivered to Extensions
        that have already been rendered.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_params = ["extension_id", "segment"]
        optional_params = ["broadcaster_id", "content", "version"]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter.")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "put",
            "/extensions/configurations",
            jwt_required=True,
            request_body=request_body,
        )

    def set_extension_required_configuration(self, broadcaster_id: str, data):
        """
        Enable activation of a specified Extension, after any required broadcaster
        configuration is correct. The Extension is identified by a client ID value
        assigned to the Extension when it is created. This is for Extensions that
        rquire broadcaster configuration before activation. Use this if, in Extension
        Capabilities, you select Custom/My Own Service.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_params = ["extension_id", "extension_version", "configuration_version"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter.")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "put",
            "/extensions/required_configuration",
            request_body=request_body,
            jwt_required=True,
            broadcaster_id=broadcaster_id,
        )

    def send_extension_pubsub_message(self, data):
        """
        Twitch provides a publish-subscribe system for your EBS to communicate
        with both the broadcaster and viewers. Calling this endpoint forwards your
        message using the same mechanism as the send JavaScript helper function. A
        message can be sent to either a specified channel or globally (all channels on
        which your extension is active).

        Extension PubSub has a rate limit of 100 requests per minute for a combination
        of Extension client ID and broadcaster ID.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_params = ["target", "broadcaster_id", "is_global_broadcast", "message"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/extensions/pubsub",
            request_body=request_body,
            jwt_required=True,
        )

    def get_extension_live_channels(
        self, extension_id: str, first: int = 20, after: Optional[str] = None
    ):
        """
        Returns one page of live channels that have installed or
        activated a specific Extension, identified by a client ID value
        assigned to the Extension when it is created. A channel that recently
        went live may take a few minutes to appear in this list, and a channel
        may continue to appear on this list for a few minutes after it stops
        broadcasting.
        """

        return self.twitch_request(
            "get",
            "/extensions/live",
            app_or_oauth_token_required=True,
            extension_id=extension_id,
            first=first,
            after=after,
        )

    def get_extension_secrets(self):
        """
        Retrieves a specified Extension's secret data consisting of
        a version and an array of secret objects. Each secret object
        contains a base64-encoded secret, a UTC timestamp when the secret
        becomes active, and a timestamp when the secret expires.
        """

        return self.twitch_request("get", "/extensions/jwt/secrets", jwt_required=True)

    def create_extension_secret(self, delay: int = 300):
        """
        Creates a JWT signing secret for a specific Extension. Also
        rotates any current secrets out of service, with enough time
        for instances of the Extension to gracefully switch over to the
        new secret. Use this function only when you are ready to install
        the new secret it returns.
        """

        return self.twitch_request(
            "post", "/extensions/jwt/secrets", jwt_required=True, delay=delay
        )

    def send_extension_chat_message(self, broadcaster_id: str, data):
        """
        Sends a specified chat message to a specified channel. The message
        will appear in the channel's chat as a normal message. The 'username'
        of the message is the Extension name.

        There is a limit of 12 messages per minute, per channel. Extension chat
        messages use the same rate-limiting functionality as the Twitch API.
        See https://dev.twitch.tv/docs/api/guide/#rate-limits
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_params = ["text", "extension_id", "extension_version"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/extensions/chat",
            jwt_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def get_extensions(
        self, extension_id: str, extension_version: Optional[str] = None
    ):
        """
        Gets information about your Extensions; either the
        current version or a specified version.
        """

        return self.twitch_request(
            "get",
            "/extensions",
            jwt_required=True,
            extension_id=extension_id,
            extension_version=extension_version,
        )

    def get_released_extensions(
        self, extension_id: str, extension_version: Optional[str] = None
    ):
        """
        Gets information a released Extension; either the
        current version or a specified version.
        """

        return self.twitch_request(
            "get",
            "/extensions/released",
            app_or_access_token_required=True,
            extension_id=extension_id,
            extension_version=extension_version,
        )

    def get_extension_bits_products(self, should_include_all: bool = False):
        "Get a list of Bits products that belongs to an Extension."

        return self.twitch_request(
            "get",
            "bits/extensions",
            app_access_token_required=True,
            should_include_all=should_include_all,
        )

    def update_extension_bits_product(self, data):
        "Add or update a Bits product that belongs to an Extension."

        required_params = ["sku", "cost", "cost.amount", "cost.type", "diplay_name"]
        optional_params = ["in_development", "expiration", "is_broadcast"]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "put",
            "/bits/extensions",
            request_body=request_body,
            app_access_token_required=True,
        )

    def create_eventsub_subscription(self, data):
        "Creates an EventSub subscription."

        required_params = ["type", "version", "condition", "transport"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter.")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/eventsub/subscriptions",
            app_access_token_required=True,
            request_body=request_body,
        )

    def delete_eventsub_subscription(self, id: str):
        "Deletes an EventSub subscription."

        return self.twitch_request(
            "delete", "/eventsub/subscriptions", app_access_token_required=True, id=id
        )

    def get_eventsub_subscriptions(
        self,
        status: Optional[str] = None,
        type: Optional[str] = None,
        after: Optional[str] = None,
    ):
        """
        Gets a list of your EventSub subscriptions. The list is paginated
        and ordered by the oldest subscription first.
        """

        return self.twitch_request(
            "get",
            "/eventsub/subscriptions",
            app_access_token_required=True,
            status=status,
            type=type,
            after=after,
        )

    def get_top_games(
        self, after: Optional[str] = None, before: Optional[str] = None, first: int = 20
    ):
        """
        Gets games sorted by number of current viewers on Twitch,
        most popular first.

        The response has a JSON payload with a data field containing
        an array of games information elements and a pagination field
        containing information required to query for more streams.
        """

        return self.twitch_request(
            "get",
            "/games/top",
            app_or_oauth_token_required=True,
            after=after,
            before=before,
            first=first,
        )

    def get_games(self, id: str, name: str):
        """
        Gets game information by game ID or name.

        The response has a JSON payload with a data field
        containing an array of games elements.
        """

        return self.twitch_request(
            "get", "/helix/games", app_or_oauth_token_required=True, id=id, name=name
        )

    def get_creator_goals(self, broadcaster_id: str):
        """
        Gets the broadcaster's list of acitve goals. Use this to
        get the current progress of each goal.
        """

        required_scope = "channel:read:goals"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get", "/goals", oauth_token_required=True, broadcaster_id=broadcaster_id
        )

    def get_hype_train_events(
        self,
        broadcaster_id: str,
        first: int = 1,
        id: Optional[str] = None,
        cursor: Optional[str] = None,
    ):
        """
        Gets the information of the most recent Hype Train of the
        given channel ID. When there is currently an active Hype Train,
         it returns information about the most recent Hype Train. After
         5 days, if no Hype Train has been active, the endpoint will return
         an empty response.
        """

        required_scope = "channel:read:hype_train"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/hypetrain/events",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            first=first,
            id=id,
            cursor=cursor,
        )

    def check_automod_status(self, broadcaster_id: str, data):
        """
        Determines whether a string message meets the channel's AutoMod
        requirements.
        """

        assert isinstance(data, dict), "data is a dict type"
        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["msg_id", "msg_text", "user_id"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter.")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/moderation/enforcements/status",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def manage_held_automod_messages(self, data):
        """
        Allow or deny a message that was held for review by AutoMod.
        In order to retrieve messages held for review, use the
        chat_moderator_actions topic via https://dev.twitch.tv/docs/pubsub.
        For more information about AutoMod, see
        https://help.twitch.tv/s/article/how-to-use-automod.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "moderator:manage:automod"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["user_id", "msg_id", "action"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/moderation/automod/message",
            oauth_token_required=True,
            request_body=request_body,
        )

    def get_automod_settings(self, broadcaster_id: str, moderator_id: str):
        """
        Gets the broadcaster's AutoMod settings, which are used to automatically block
        inappropriate or harassing messages from appearing in the broadcaster's chat
        room.
        """

        required_scope = "moderator:read:automod_settings"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/moderation/automod/settings",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def update_automod_settings(
        self, broadcaster_id: str, moderator_id: str, data: Dict[str, int]
    ):
        """
        Updates the broadcaster's AutoMod settings, which are used to automatically
        block inappropriate or harassing messages from appearing in the broadcaster's
        chat room.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "moderator:manage:automod_settings"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        optional_params = [
            "aggression",
            "bullying",
            "disability",
            "misogyny",
            "overall_level",
            "race_ethnicity_or_religion",
            "sex_based_terms",
            "sexuality_sex_or_gender",
            "swearing",
        ]
        request_body = {
            key: value for (key, value) in data.items() if key in optional_params
        }
        return self.twitch_request(
            "put",
            "/moderation/automod/settings",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def get_banned_events(
        self,
        broadcaster_id: str,
        user_id: Optional[Union[str, List]] = None,
        after: Optional[str] = None,
        first: str = "20",
        user_id_as_list: bool = False,
    ):
        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        return self.twitch_request(
            "get",
            "/moderation/banned/events",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
            after=after,
            first=first,
        )

    def get_banned_users(
        self,
        broadcaster_id: str,
        user_id: Optional[Union[str, List]] = None,
        first: str = "1",
        after: Optional[str] = None,
        before: Optional[str] = None,
        user_id_as_list: bool = False,
    ):
        "Returns all banned and timed-out users for a channel"

        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        return self.twitch_request(
            "get",
            "/moderation/banned",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
            first=first,
            after=after,
            before=before,
        )

    def ban_user(self, broadcaster_id: str, moderator_id: str, data: Dict[str, Any]):
        """
        Bans a user from participating in a broadcaster's chat room, or puts
        them in a timeout.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "moderator:manage:banned_users"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["data", "reason", "user_id"]
        optional_params = ["duration"]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "post",
            "/moderation/bans",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def unban_user(self, broadcaster_id: str, moderator_id: str, user_id: str):
        "Removes the ban or timeout that was placed on the specified user."

        required_scope = "moderator:manage:banned_users"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "delete",
            "/moderation/bans",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
            user_id=user_id,
        )

    def get_blocked_terms(
        self,
        broadcaster_id: str,
        moderator_id: str,
        first: int = 20,
        after: Optional[str] = None,
    ):
        """
        Gets the broadcaster's list of non-private, blocked words or phrases.
        These are the terms that the broadcaster or moderator added manually,
        or that were denied by AutoMod.
        """

        required_scope = "moderator:read:blocked_terms"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/moderation/blocked_terms",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
            first=first,
            after=after,
        )

    def add_blocked_term(
        self, broadcaster_id: str, moderator_id: str, data: Dict[str, str]
    ):
        """
        Adds a word or phrase to the broadcaster's list of blocked terms.
        These are the terms that broadcasters don't want used in their
        chat room.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "moderator:manage:blocked_terms"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["text"]
        if required_params[0] not in data.keys():
            raise InvalidRequestException(
                f"{required_params[0]} is a required body parameter"
            )

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post",
            "/moderation/blocked_terms",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def remove_blocked_term(self, broadcaster_id: str, id: str, moderator_id: str):
        """
        Removes the word or phrase that the broadcaster is blocking user from using
        in their chat room.
        """

        required_scope = "moderator:manage:blocked_terms"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "delete",
            "/moderation/blocked_terms",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
            moderator_id=moderator_id,
        )

    def get_moderators(
        self,
        broadcaster_id: str,
        user_id: Optional[Union[str, Dict]] = None,
        first: str = "20",
        after: Optional[str] = None,
        user_id_as_list: bool = True,
    ):
        """
        Returns all moderators in a channel. Note: This endpoint does
        not return the broadcaster in the response, as broadcaster are
        channel owners and have all permissions of moderators implicitly.
        """

        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        return self.twitch_request(
            "get",
            "/moderation/moderators",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
            first=first,
            after=after,
        )

    def get_moderator_events(
        self,
        broadcaster_id: str,
        user_id: Optional[Union[str, List]] = None,
        after: Optional[str] = None,
        first: str = "20",
        user_id_as_list: bool = False,
    ):
        """
        Returns a list of moderators or users added and removed as
        moderators from a channel.
        """

        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        return self.twitch_request(
            "get",
            "/moderation/moderator/events",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
            after=after,
            first=first,
        )

    def get_polls(
        self,
        broadcaster_id: str,
        id: Optional[str] = None,
        after: Optional[str] = None,
        first: str = "20",
    ):
        """
        Get information about all polls or specific polls for a Twitch channel.
        Poll information is available for 90 days.
        """

        required_scope = "channel:read:polls"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/polls",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
            after=after,
            first=first,
        )

    def create_poll(self, data: Dict[str, Any]):
        "Create a poll for a specific Twitch channel."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:polls"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = [
            "broadcaster_id",
            "title",
            "choices",
            "choices.title",
            "duration",
        ]
        optional_params = [
            "bits_voting_enabled",
            "bits_per_vote",
            "channel_points_voting_enabled",
            "channel_points_per_vote",
        ]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "post", "/polls", oauth_token_required=True, request_body=request_body
        )

    def end_poll(self, data: Dict[str, str]):
        "End a poll that is currently active."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:polls"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["broadcaster_id", "id", "status"]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "patch", "/polls", oauth_token_required=True, request_body=request_body
        )

    def get_predictions(
        self,
        broadcaster_id: str,
        id: Optional[str] = None,
        after: Optional[str] = None,
        first: str = "20",
    ):
        """
        Get information about all Channel Points Predictions or specific
        Channel Points Predictions for a Twitch channel. Resulsts are ordered
        by most recent, so it can be assumed that the currently active
        or locked Prediction will be the first item.
        """

        required_scope = "channel:read:predictions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/predictions",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
            after=after,
            first=first,
        )

    def create_prediction(self, data: Dict[str, Any]):
        "Creates a Channel Points Prediction for a specific Twich channel."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:predictions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = [
            "broadcaster_id",
            "title",
            "outcomes",
            "outcome.title",
            "prediction_window",
        ]
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {
            key: value for (key, value) in data.items() if key in required_params
        }
        return self.twitch_request(
            "post", "/predictions", oauth_token_required=True, request_body=request_body
        )

    def end_prediction(self, data: Dict[str, str]):
        """
        Lock, resolve, or cancel a Channel Points Prediction.
        Active Predictions can be updated to be 'locked', 'resolved',
        or 'canceled'. Locked predictions can be be update to be
        'resolved' or 'canceled'.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:prediction"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["broadcaster_id", "id", "status"]
        optional_params = ["winning_outcome_id"]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "patch",
            "/predictions",
            oauth_token_required=True,
            request_body=request_body,
        )

    def get_channel_stream_schedule(
        self,
        broadcaster_id: str,
        id: Optional[str] = None,
        start_time: Optional[str] = None,
        utc_offset: Optional[str] = None,
        first: int = 20,
        after: Optional[str] = None,
    ):
        """
        Gets all scheduled broadcasts or specific scheduled broadcasts from a
        channel's stream schedule. Scheduled broadcasts are defined as 'stream
        segments' in the API."""

        return self.twitch_request(
            "get",
            "/schedule",
            app_or_access_token_required=True,
            broadcaster_id=broadcaster_id,
            id=id,
            start_time=start_time,
            utc_offset=utc_offset,
            first=first,
            after=after,
        )

    @retry
    def get_channel_icalendar(self, broadcaster_id: str):
        """
        Gets all scheduled broadcasts ffrom a channel's stream schedule as
        an iCalendar.
        """

        # from twitch's reference documentation, this doesn't require
        # any form of authorization
        # therefore this deserves it's own request format
        # tenacity library for it's own personal retry
        endpoint = "/schedule/icalendar"
        url = add_params_to_uri(
            self.TWITCH_API_BASE_URL + endpoint, [("broadcaster_id", broadcaster_id)]
        )
        response = requests.get(url)
        if response.status_code == 200:
            return response.text

    def create_channel_stream_schedule_segment(
        self, broadcaster_id: str, data: Dict[str, Any]
    ):
        """
        Create a single scheduled broadcast or recurring scheduled broadcast for
        a channel's stream schedule.
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:scedule"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["start_time", "timezone", "is_recurring"]
        optional_params = ["duration", "category_id", "title"]
        params = required_params + optional_params
        for i in required_params:
            if i not in data.keys():
                raise InvalidRequestException(f"{i} is a required body parameter")

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "post",
            "/schedule/segment",
            oauth_token_required=True,
            request_body=request_body,
        )

    def update_channel_stream_schedule_segment(
        self,
        broadcaster_id: str,
        is_vacation_enabled: Optional[bool] = None,
        vacation_start_time: Optional[str] = None,
        timezone: Optional[str] = None,
    ):
        """
        Update a single scheduled broadcast or a recurring scheduled broadcast
        for a channel's stream schedule.
        """

        if is_vacation_enabled is not None:
            if is_vacation_enabled:
                if not all([vacation_start_time, vacation_end_time, timezone]):
                    raise InvalidRequestException(
                        "If is_vacation_enabled is set to True, vacation_start_time, "
                        "vacation_end_time and timezone parameters are required."
                    )

        required_scope = "channel:manage:schedule"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "patch",
            "/schedule/settings",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            is_vacation_enabled=is_vacation_enabled,
            vacation_start_time=vacation_start_time,
            timezone=timezone,
        )

    def delete_channel_stream_schedule_segment(self, broadcaster_id: str, id: str):
        """
        Delete a single scheduled broadcast or a recurring scheduled broadcast
        for a channel's stream schedule.
        """

        required_scope = "channel:manage:scedule"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "delete",
            "/schedule/segment",
            oauth_token_required=oauth_token_required,
            broadcaster_id=broadcaster_id,
            id=id,
        )

    def search_catgories(
        self, query: str, first: int = 20, after: Optional[str] = None
    ):
        """
        Returns a list of games or categories that match the query via
        name either entirely or partially.
        """

        # TODO: query parameter needs to be uri encoded
        return self.twitch_request(
            "get",
            "/search/categories",
            app_or_oauth_token_required=True,
            query=query,
            first=first,
            after=after,
        )

    def search_channels(
        self,
        query: str,
        first: int = 20,
        after: Optional[str] = None,
        live_only: bool = False,
    ):
        """
        Returns a list of channels (users who have streamed within
        the past 6 months) that match the query via channel name or
        description either entirely or partially. Results include both
        live and offline channels. Online channels will have additional
        metadata (e.g. started_at, tag_ids)
        """

        return self.twitch_request(
            "get",
            "/search/channels",
            app_or_oauth_token_required=True,
            query=query,
            first=first,
            after=after,
            live_only=live_only,
        )

    def get_soundtrack_current_track(self, broadcaster_id: str):
        "[BETA] Gets the Soundtrack track that the broadcaster is playing."

        return self.twitch_request(
            "get",
            "/soundtrack/current_track",
            app_or_oauth_token=True,
            broadcaster_id=broadcaster_id,
        )

    def get_soundtrack_playlist(self, id: str):
        "[BETA] Gets a Soundtrack playlist, which includesits list of tracks."

        return self.twitch_request(
            "get", "/soundtrack/playlist", app_or_oauth_token_required=True, id=id
        )

    def get_soundtrack_playlists(self):
        """
        [BETA] Gets a list of Soundtrack playlists.

        The list contains information about the playlists, such
        as their titles and descriptions. To get a playlist's tracks,
        call https://dev.twitch.tv/docs/api/reference#get-soundtrack-playlist,
         and specify the playlist's id.
        """

        return self.twitch_request(
            "get",
            "/soundtrack/playlists",
            app_or_oauth_token_required=True,
        )

    def get_stream_key(self, broadcaster_id: str):
        "Gets the channel stream key for a user."

        required_scope = "channel:read:stream_key"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/streams/key",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def get_streams(
        self,
        after: Optional[str] = None,
        before: Optional[str] = None,
        first: int = 20,
        game_id: Optional[Union[str, List]] = None,
        language: Optional[str] = None,
        user_id: Optional[Union[str, List]] = None,
        user_login: Optional[Union[str, List]] = None,
        game_id_as_list: bool = False,
        user_id_as_list: bool = False,
        user_login_as_list: bool = False,
    ):
        """
        Gets information about active streams. Streams are returned sorted by
        number of current viewers, in descending order. Across multiple pages
        of results, there may be duplicate or missing stream, as viewers join
        and leave streams.

        The response has a JSON payload with a data field containing an array
        of stream information elements and a pagination field containing information
        required to query for more streams.
        """

        if game_id_as_list:
            assert isinstance(game_id, list), "game_id should be a list type"
        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        if user_login_as_list:
            assert isinstance(user_login, list), "user_login should be a list type"

        return self.twitch_request(
            "get",
            "/streams",
            app_or_oauth_access_token_required - True,
            game_id=game_id,
            user_id=user_id,
            user_login=user_login,
            language=language,
            first=first,
            after=after,
        )

    def get_followed_streams(
        self, user_id: str, after: Optional[str] = None, first: int = 20
    ):
        """
        Gets information about active streams belonging to channels that the
        authenticated user follows. Streams are returned sorted by number of current
        viewers, in descending order. Across multiple pages of results, there may be
        duplicate or missing streams, as viewers join and leave streams,
        """
        # twitch reference has first parameter's default value as 100
        # but pretty sure it's 20

        required_scope = "user:read:follows"
        if required_scope not in self.required_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/streams/followed",
            oauth_token_required=True,
            user_id=user_id,
            after=after,
            first=first,
        )

    def create_stream_marker(self, data: Dict[str, str]):
        """
        Creates a marker in the stream of a user specified by user ID. A marker is
        an arbitrary point in a stream that the broadcaster wants to mark;
        e.g., to easily return to later. The marker is created at the current
        timestamp in the live broadcast when the request is processed. Markers
        can be created by the stream owner or editors. The user creating the marker
        is identified by a Bearer token.

        Markers cannot be created in some cases (an error will occur):
            * If the specified user's stream is not live

            * If VOD (past broadcast) storage is not enabled for the stream.

            * For premieres (live, first-viewing events that combin uploaded
              videos with live chat).

            * For reruns (subsequent (not live) streaming of any past broadcast,
              including past premieres).
        """

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:broadcast"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        required_params = ["user_id"]
        optional_params = ["description"]
        params = required_params + optional_params
        if required_params[0] not in data.keys():
            raise InvalidRequestException(
                f"{required_params[0]} is a required body parameter"
            )

        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.twitch_request(
            "post",
            "/streams/markers",
            oauth_token_required=True,
            request_body=request_body,
        )

    def get_stream_markers(
        self,
        user_id: Optional[str] = None,
        video_id: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        first: str = "20",
    ):
        """
        Gets a list of markers for either a specified user's most recent stream or
        a specified VOD/video (stream), ordered by recency. A marker is an
        arbitrary point in a stream that the broadcaster wants to mark;
        e.g., to easily return to later. The only markers returned are those
        created by the user identified by the Bearer token.

        The response has a JSON payload with a data field containing an array
        of marker information elements and a pagination field containing information
        required to query for more follow information.
        """

        if all([user_id, video_id]):
            raise InvalidRequest("Only one of user_id and video_id must be specified")

        required_scope = "user:read:broadcast"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/streams/markers",
            oauth_token_required=True,
            user_id=user_id,
            video_id=video_id,
            after=after,
            before=before,
            first=first,
        )

    def get_broadcaster_subscriptions(
        self,
        broadcaster_id: str,
        user_id: Optional[Union[List, str]] = None,
        after: Optional[str] = None,
        first: str = 20,
        user_id_as_list: bool = False,
    ):
        "Gets all of a broadcaster's subscriptions."

        if user_id_as_list:
            assert isinstance(user_id, list), "user_id should be a list type"
        required_scope = "channel:read:subscriptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{requied_scope}] scope required")

        return self.twitch_request(
            "get",
            "/subscriptions",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
            after=after,
            first=first,
        )

    def check_user_subscription(self, broadcaster_id: str, user_id: str):
        """
        Checks if a specific user (user_id) is subscribed to a specific
        channel (broadcaster_id).
        """

        required_scope = "user:read:subscriptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "subscriptions/user",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            user_id=user_id,
        )

    def get_all_stream_tags(
        self,
        after: Optional[str] = None,
        first: int = 20,
        tag_id: Optional[Union[List, str]] = None,
        tag_id_as_list: bool = False,
    ):
        """
        Gets the list of all stream tags that Twitch defines. You can also filter
        the list by one or more tag IDs.

        For an online list of the possible tags, see https://www.twitch.tv/directory/all/tags
        """

        if all([after, tag_id]):
            raise InvalidRequestException(
                "after and tag_id parameters are not used together"
            )

        return self.twitch_request(
            "get",
            "/tags/streams",
            oauth_token_required=True,
            after=after,
            first=first,
            tag_id=tag_id,
        )

    def get_stream_tags(self, broadcaster_id: str):
        "Gets the list of stream tags that are set on the specified channel."

        return self.twitch_request(
            "get",
            "/streams/tags",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def replace_stream_tags(
        self, broadcaster_id: str, data: Optional[Dict[str, List]] = None
    ):
        """
        Applies one or more tags to the specified channel, overwriting any
        existing tags. If the request does not specify tags, all existing tags
        are removed from the channel.

        NOTE: You may not specify automatic tags; the call will fail if you
        specify automatic tags. Automatic tags are tags that Twitch applies
        to the channel. For a list of automatic tags, see
        https://www.twitch.tv/directory/all/tags.

        To get the list programmatically, see
        https://dev.twitch.tv/docs/api/reference#get-all-streams-tags.

        Tags expire 72 hours after they are applied, unless the channel is live within
        that time period. If the channel is live within the 72-hour window, the
        72-hour clock restarts when the channel goes offline. The expiration period
        is subject to change.
        """

        data = data if data is None else {}
        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:broadcast"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        optional_params = ["tag_ids"]
        request_body = {
            key: value for (key, value) in data.items() if key in optional_params
        }
        return self.twitch_request(
            "put",
            "/streams/tags",
            oauth_token_required=True,
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def get_channel_teams(self, broadcaster_id: str):
        """
        Retrieves a list of Twitch Teams of which the specified channel/broadcaster
        is a member.
        """

        return self.twitch_request(
            "get",
            "/teams/channel",
            app_or_oauth_token_required=True,
            broadcaster_id=broadcaster_id,
        )

    def get_teams(self, name: Optional[str] = None, id: Optional[str] = None):
        "Gets information for a specific Twitch Team."

        return self.twitch_request(
            "get",
            "/helix/teams",
            app_or_oauth_access_token_required=True,
            name=name,
            id=id,
        )

    def get_users(
        self,
        id: Optional[Union[List, str]] = None,
        login: Optional[Union[List, str]] = None,
        id_as_list: bool = False,
        login_as_list: bool = False,
    ):
        """
        Gets information about one or more specified Twitch user. Users are identified
        by optional user IDs and/or login name. If neither a user ID nor a login
        name is specified, the user is looked up by Bearer token.

        The response has a JSON payload with a data field containing an array
        of user-information elements.
        """

        if id_as_list:
            assert isinstance(id, list), "id should be a list type"
        if login_as_list:
            assert isinstance(login, list), "login should be a list type"
        required_scope = "user:read:email"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/helix/users",
            app_or_oauth_access_token_required=True,
            id=id,
            login=login,
        )

    def update_user(self, description: Optional[str] = None):
        """
        Updates the desceiption of a user specified by a Bearer token.
        Note that the description parameter is optional should other
        updatable parameters become available in the future. If the description
        parameter is not provided, no update will occur and the current user data
        is returned.
        """

        required_scope = "user:edit"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "put", "/users", oauth_token_required=True, description=description
        )

    def get_users_follows(
        self,
        after: Optional[str] = None,
        first: int = 20,
        from_id: Optional[str] = None,
        to_id: Optional[str] = None,
    ):
        """
        Gets information on follow relationships between two Twitch users.
        Information returned is sorted in order, most recent follow first.

        The response has a JSON paylaod with a data field containing an array
        of follow relationship elements and a pagination field containing
        information required to query for more follow information.
        """

        if not any([from_id, to_id]):
            raise InvalidRequestException(
                "At minimum, from_id or to_id must be provided for " "query to be valid"
            )

        return self.twitch_request(
            "get",
            "/users/follows",
            app_or_oauth_token_required=True,
            after=after,
            first=first,
            from_id=from_id,
            to_id=to_id,
        )

    def get_user_block_list(
        self, broadcaster_id: str, first: int = 20, after: Optional[str] = None
    ):
        """
        Gets a specified user's block list. The list is sorted by when the block
        occurred in descending order (i.e. most recent block first).
        """

        required_scope = "user:read:blocked_user"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "get",
            "/users/blocks",
            oauth_token_required=True,
            broadcaster_id=broadcaster_id,
            first=first,
            after=after,
        )

    def block_user(
        self,
        target_user_id: str,
        source_context: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        "Blocks the specified user on behalf of the authenticated user."

        required_scope = "user:manage:blocked_user"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"[{required_scope}] scope required")

        return self.twitch_request(
            "put",
            "/users/blocks",
            oauth_token_required=True,
            target_user_id=target_user_id,
            source_context=source_context,
            reason=reason,
        )

    def unblock_user(self, target_user_id: str):
        "Unblocks the specified user on behalf of the authenticated user."

        required_scope = "user:manage:blocked_users"
        if required_scope not in self.twitch_scope:
            raise ScopeError("[{required_scope}] scope required")

        return self.twitch_request(
            "delete",
            "/users/blocks",
            oauth_token_required=True,
            target_user_id=target_user_id,
        )

    def get_user_extensions(self):
        """
        Gets a list of all extensions (both active and inactive) for a
        specified user, identified by a Bearer token.

        The response has a JSON payload with a data field containing an
        array of user-information element.
        """

        required_scope = "user:read:broadcast"
        if required_scope not in self.twitch_scope:
            raise ScopeError("[{required_scope}] scope required")

        return self.twitch_request(
            "get", "/users/extensions/list", oauth_tokne_required=True
        )

    def get_user_active_extensions(self, user_id: Optional[str] = None):
        """
        Gets information about active extensions installed by a specified user,
        identified by a user ID or Bearer token.
        """

        return self.twitch_request(
            "get", "/users/extensions", oauth_token_required=True, user_id=user_id
        )

    def update_user_extensions(self, data: Dict[str, Any]):
        """
        Updates the activation state, extension ID, and/or version number of
        installed extensions for a specific user, identified by a Bearer token.
        If you try to activate a given extension under multiple extension types,
        the last write wins (and there is no guarantee of write order).
        """

        # twitch documentation hasn't yet provided documentation
        # for request body keys
        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "user:edit:broadcast"
        if required_scope not in self.twitch_request:
            raise ScopeError(f"[{required_scope}] scope required")

        request_body = data

        return self.twitch_request(
            "put",
            "/users/extensions",
            oauth_token_required=True,
            request_body=request_body,
        )

    def get_videos(
        self,
        id: Optional[Union[List, str]] = None,
        user_id: Optional[str] = None,
        game_id: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        first: Optional[str] = None,
        language: Optional[str] = None,
        period: Optional[str] = None,
        sort: Optional[str] = None,
        type: Optional = None,
        id_as_list: bool = False,
    ):
        """
        Gets video information by one or more video IDs, user ID, or game ID.
        For lookup by user or game, several filters available that can be
        specified as query parameters.
        """

        if not any([id, user_id, game_id]):
            raise InvalidRequestException(
                "Each request must specify one or more video id's, "
                "one user_id, or one game_id"
            )

        if id is not None:
            if id_as_list:
                assert isinstance(id, list), "id should be a list type"
            if any([after, before, first, language, period, sort, type]):
                raise InvalidRequestException(
                    "Optional query parameters can be used if the request "
                    "specifies a user_id or game_id, not video id."
                )

        return self.twitch_request(
            "get",
            "/videos",
            app_or_oauth_token_required=True,
            id=id,
            user_id=user_id,
            game_id=game_id,
            after=after,
            before=before,
            first=first,
            language=language,
            period=period,
            sort=sort,
            type=type,
        )

    def delete_videos(self, id: str):
        """
        Deletes one or more videos. Videos are past broadcasts, Highlights
        or uploads.

        Invalid Video IDs will be ignored (i.e. IDs proveided that do not
        have a video associated with it). If the OAuth user token does not
        have permission to delete even one of the valid Video IDs, no videos
        will be deleted and the response will return a 401.
        """

        required_scope = "channel:manage:videos"
        if required_scope not in self.twitch_scope:
            raise ScopeError("[{required_scope}] scope required")

        return self.twitch_request(
            "delete", "/videos", oauth_token_required=True, id=id
        )
