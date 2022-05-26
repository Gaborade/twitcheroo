import sys
from typing import Optional, Dict, Any, Union
from oauth import ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow
from exceptions import TwitchAuthException, InvalidRequestException
from authlib.common.urls import add_params_to_uri


class Twitch:
    TWITCH_API_BASE_URL: str = "https://api.twitch.tv/helix"
    AUTH_OBJECTS: List[Any] = [
        ClientCredentials,
        AuthorizationCodeFlow,
        OIDCAuthorizationCodeFlow,
    ]

    def __init__(self, auth, max_retries=3, timeout=None):
        if not any(
            isinstance(auth, auth_object) for auth_object in Twitch.AUTH_OBJECTS
        ):
            raise TwitchAuthException(
                f"""Authentication class <{auth.__class__.__name__}> not supported by API.
                 Use ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow 
                authentication classes"""
            )

        self.twitch_session, self.twitch_scope = auth()
        self.max_retries = max_retries
        self.timeout = timeout

    @staticmethod
    def _apply_exponential_backoff():
        raise NotImplementedError

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
        assert_msg = """
                      Either of oauth_token_required, app_access_token_required or 
                      app_or_oauth_token_required kwargs should be set to True 
                      for any Twitch endpoint method created.
                      """
        assert any(
            [
                oauth_token_required,
                app_access_token_required,
                app_or_oauth_token_required,
            ]
        ), assert_msg

        if app_access_token_required:
            if not isinstance(self.twitch_session, ClientCredentials):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an app access token"
                )
        if oauth_token_required:
            if not isinstance(self.twitch_session, AuthorizationCodeFlow):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an oauth token"
                )
        if app_or_oauth_token_required:
            if not isinstance(
                self.twitch_session, ClientCredentials
            ) and not isinstance(self.session, AuthorizationCodeFlow):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint "
                    "requires an app access token or oauth token"
                )
        if jwt_required:
            if not isinstance(self.twitch_session, OIDCAuthorizationCodeFlow):
                raise TwitchAuthException(
                    f"{self.TWITCH_API_BASE_URL}{endpoint} endpoint requires a jwt token"
                )

        fragments = []
        for k, v in query_parameters.copy().items():
            if isinstance(v, list):
                pop_list = query_parameters.pop(k)
                fragments += [(k, element) for element in pop_list]
        build_url = [
            (key, value) for key, value in query_parameters.items() if value is not None
        ]
        build_url += fragments
        url = add_params_to_uri(self.TWITCH_API_BASE_URL + endpoint, build_url)

        retries = self.max_retries
        # TODO: there should be backoffs and random jitters
        while retries > 0:
            try:
                if request_body is not None:
                    response = self.twitch_session.request(
                        method, url, body=request_body
                    )
                else:
                    response = self.twitch_session.request(method, url)
            except Exception:
                retries -= 1
                # this bit is overengineered. can just do Exception as e
                # then raise e instead of using sys.exc_info, achieves the same thing
                # only thing is, should i add tracebacks?
                # only valid reason for maybe using sys.exc_info will be to raise different error
                # messages depending on the type of error say HTTP or URLError as shown below
                recent_exception = sys.exc_info()
                if retries == 0:
                    exception_class, exception_message = recent_exception[:2]
                    if exception_class == HTTPError:
                        # raise my own personal error here but pass now
                        pass
                    elif exception_class == URLError:
                        pass
                    else:
                        raise exception_class(exception_message)
            else:
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 400:
                    raise BadRequest(response.reason)
                elif response.status_code == 500:
                    raise TwitchServerError(response.reason)
                elif response.status_code == 401:
                    raise UnAuthorizedException(response.reason)

    def start_commercial(self, data):
        "Start a commerical on a specified channel"

        assert isinstance(data, dict), "data should be a dict type"

        required_scope = "channel:edit:commercial"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
        status: str = None,
        sort: str = "OLDEST",
        after: str = None,
        first: int = 20,
    ):
        """
        Returns Custom Reward Redemption objects for a Custom Reward
        on a channel that was created by the same client_id.
        """

        required_scope = "channel:read:redemptions"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
                    f"<{required_scope}> scope required if moderator_id is provided"
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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
        after: str = None,
        before: str = None,
        ended_at: str = None,
        first: int = 20,
        started_at: str = None,
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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
        "Return all user banned and un-banned events for a channel."
        # if just requesting for a single user id, user_id is a string,
        # requesting for multiple users user_id should be an iterable
        # eg of a hypothetical request here
        # twitch.get_banned_events("198704263", user_id=[32, 12, 13])
        # where first parameter is the broadcaster_id and the second is for user_id passed as a list
        # or an iterable type

        required_scope = "moderation:read"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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
        after: str = "20",
    ):
        """
        Get information about all polls or specific polls for a Twitch channel.
        Poll information is available for 90 days.
        """

        required_scope = "channel:read:polls"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"<{required_scope}> scope required")

        return self.request(
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
            raise ScopeError(f"<{required_scope}> scope required")

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

    def end_poll(self, data: Data[str, str]):
        "End a poll that is currently active."

        assert isinstance(data, dict), "data should be a dict type"
        required_scope = "channel:manage:polls"
        if required_scope not in self.twitch_scope:
            raise ScopeError(f"<{required_scope}> scope required")

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
            raise ScopeError(f"<{required_scope} scope required")

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
            raise ScopeError(f"<{required_scope}> scope required")

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

    def end_prediction(self):
        "Lock, resolve, or cancel a Channel Points Prediction."
        pass

    def get_channel_stream_schedule(self):
        """
        Gets all scheduled broadcasts or specific scheduled broadcasts from a
        channel's stream schedule.
        """
        pass

    def get_channel_icalendar(self):
        """
        Gets all scheduled broadcasts ffrom a channel's stream schedule as
        an iCalendar.
        """
        pass

    def update_channel_stream_schedule(self):
        "Update the settings for a channel's stream schedule."
        pass

    def create_channel_stream_schedule_segment(self):
        """
        Create a single scheduled broadcast or recurring scheduled broadcast for
        a channel's stream schedule.
        """
        pass

    def update_channel_stream_schedule_segment(self):
        """
        Update a single scheduled broadcast or a recurring scheduled broadcast
        for a channel's stream schedule.
        """
        pass

    def delete_channel_stream_schedule_segment(self):
        """
        Delete a single scheduled broadcast or a recurring scheduled broadcast
        for a channel's stream schedule.
        """
        pass

    def search_catgories(self):
        """
        Returns a list of games or categories that match the query via
        name either entirely or partially.
        """
        pass

    def search_channels(self):
        """
        Returns a list of channels that match the query  via channel name or
        description either entirely or partially.
        """
        pass

    def get_soundtrack_current_track(self):
        "[BETA] Gets the Soundtrack track that the broadcaster is playing."
        pass

    def get_soundtrack_playlist(self):
        "[BETA] Gets a Soundtrack playlist, which includesits list of tracks."
        pass

    def get_get_soundtrack_playlists(self):
        "[BETA] Gets a list of Soundtrack playlists."
        pass

    def get_stream_key(self):
        "Gets the channel stream key for a user."
        pass

    def get_streams(self):
        """
        Gets information about active streams. Streams are returned sorted by
        number of current viewers, in descending order.
        """
        pass

    def get_followed_streams(self):
        """
        Gets information about active streams belonging to channels that the
        authenticated user follows.
        """
        pass

    def create_stream_marker(self):
        """
        Creates a marker in the stream of a user specified by user ID. A marker is
        an arbitrary point in a stream that the broadcaster wants to mark.
        """
        pass

    def get_stream_markers(self):
        """
        Gets a list of markers for either a specified user's most recent stream or
        a specified VOD/video (stream), ordered by recency. A marker is an
        arbitrary point in a stream that the broadcaster wants to mark.
        """
        pass

    def get_broadcaster_subscriptions(self):
        "Gets all of a broadcaster's subscriptions."
        pass

    def check_user_subscription(self):
        "Checks if a specific user is subscribed to a specific channel."
        pass

    def get_all_stream_tags(self):
        """
        Gets the list of all stream tags that Twitch defines. You can also filter
        the list by one or more tag IDs.
        """
        pass

    def get_stream_tags(self):
        "Gets the list of stream tags that are set on the specified channel."
        pass

    def replace_stream_tags(self):
        """
        Applies one or more tags to the specified channel, overwriting any
        existing tags.
        """
        pass

    def get_channel_teams(self):
        """
        Retrieves a list of Twitch Teams of which the specified channel/broadcaster
        is a member.
        """
        pass

    def get_teams(self):
        "Gets information for a specific Twitch Team."
        pass

    def get_users(self):
        """
        Gets information about one or more specified Twitch user. Users are identified
        by optional user IDs and/or login name.
        """
        pass

    def update_user(self):
        "Updates the desceiption of a user specified by a Bearer token."
        pass

    def get_users_follows(self):
        """
        Gets information on follow relationships between two Twitch users.
        Information returned is sorted in order, most recent follow first.
        """
        pass

    def get_user_block_list(self):
        """
        Gets a specified user's block list. The list is sorted by when the block
        occurred in descending order (i.e. most recent block first).
        """
        pass

    def block_user(self):
        "Blocks the specified user on behalf of the authenticated user."
        pass

    def unblock_user(self):
        "Unblocks the specified user on behalf of the authenticated user."
        pass

    def get_user_extensions(self):
        """
        Gets a list of all extensions (both active and inactive) for a
        specified user, identified by a Bearer token.
        """
        pass

    def get_user_active_extensions(self):
        """
        Gets information about active extensions installed by a specified user,
        identified by a user ID or Bearer token.
        """
        pass

    def update_user_extensions(self):
        """
        Updates the activation state, extension ID, and/or version number of
        installed extensions for a specific user, identified by a Bearer token.
        """
        pass

    def get_videos(self):
        "Gets video information by one or more video IDs, user ID, or game ID."
        pass

    def delete_videos(self):
        """
        Deletes one or more videos. Videos are past broadcasts, Highlights
        or uploads.
        """
        pass
