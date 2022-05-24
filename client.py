import sys
from typing import Optional
from oauth import ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow
from exceptions import TwitchAuthException, InvalidRequestException
from authlib.common.urls import add_params_to_uri


class Twitch:
    TWITCH_API_BASE_URL: str = "https://api.twitch.tv/helix"
    AUTH_OBJECTS = [ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow]

    def __init__(self, auth, max_retries=3, timeout=None):
        if not any(isinstance(auth, auth_object) for auth_object in self.AUTH_OBJECTS):
            raise TwitchAuthException(
                f"""Authentication class <{auth.__class__.__name__}> not supported by API.
                 Use ClientCredentials, AuthorizationCodeFlow, OIDCAuthorizationCodeFlow 
                authentication classes"""
            )
        self.twitch_session = auth()  # could be auth(), due to __call__
        # or self.session, self.scopes = auth()
        self.max_retries = max_retries
        self.twitch_scope = auth.scope.split()
        self.timeout = timeout

    @staticmethod
    def _apply_exponential_backoff():
        raise NotImplementedError

    def request(
        self,
        method: str,
        endpoint: str,
        request_body=None,
        jwt_required=False,
        oauth_token_required=False,
        app_access_token_required=False,
        app_or_oauth_token_required=False,
        **query_parameters,
    ):
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

        if "channel:edit:commercial" not in self.twitch_session.scopes:
            return ScopeError("<channel:edit:commercial> scope required")
        required_params = ["broadcaster_id", "length"]
        request_body = {
            key: value for (key, value) in data.items if key in required_params
        }
        return self.request(
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

        if "analytics:read:extensions" not in self.twitch_session.scopes:
            raise ScopeError("<analytics:read:extensions> scope required")
        if started_at and not ended_at or ended_at and not started_at:
            raise Exception(
                "started_at and ended_at optional parameters always used together"
            )
        return self.request(
            "get",
            "/analytics/extensions",
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

        if "analytics:read:games" not in self.twitch_session.scopes:
            raise ScopeError("<analytics:read:games> scope required")

        if started_at and not ended_at or ended_at and not started_at:
            raise Exception(
                "started_at and ended_at optional parameters always used together"
            )

        return self.request(
            "get",
            "/analytics/games",
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
        period: str = "all",
        started_at: str = None,
        user_id: str = None,
    ):
        """
        Gets a ranked list of Bits leaderboard information for an authorized
        broadcaster.
        """

        if "bits:read" not in self.twitch_session.scopes:
            raise ScopeError("<bits:read> scope required")
        return self.request(
            "get",
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

        return self.request("get", "/bits/cheermotes", broadcaster_id=broadcaster_id)

    def get_extension_transactions(
        self, extension_id: str, id: str = None, after: str = None, first: int = 20
    ):
        """
        Gets the list of Extension transactions for a given extension. This allows
        Extension back-end servers to fetch a list of transactions that have occurred
        for their Extension across all of Twitch.
        """

        return self.request(
            "get",
            "/extensions/transactions",
            extension_id=extension_id,
            id=id,
            after=after,
            first=first,
        )

    def get_channel_information(self, broadcaster_id: str):
        """Gets channel information for users."""

        return self.request("get", "/channels", broadcaster_id=broadcaster_id)

    def modify_channel_information(self, broadcaster_id: str, data):
        """Modifies channel information for users."""

        assert isinstance(data, dict), "data should be a dict type"
        if "channel:manage:broadcast" not in self.session.scopes:
            raise ScopeError("<channel:manage:broadcast> scope required")

        request_body = {}
        body_params = ["game_id", "broadcaster_language", "title", "delay"]
        request_body = {
            key: value for (key, value) in data.items() if key in body_params
        }
        return self.request(
            "patch",
            "/channels",
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def get_channel_editors(self, broadcaster_id: str):
        """
        Gets a list of users who have editor permissions for a specific
        channel.
        """

        if "channel:read:editors" not in self.session.scopes:
            raise ScopeError("<channel:read:editors> scope required")
        return self.request("get", "/channel/editors", broadcaster_id=broadcaster_id)

    def create_custom_rewards(self, broadcaster_id, data):
        "Creates a Custom Reward on a channel."

        if "channel:manage:redemptions" not in self.session.scopes:
            raise ScopeError("<channel:manage:redemptions> scope required")
        assert isinstance(data, dict), "data should be a dict type"

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
        return self.request(
            "post",
            "/channel_points/custom_rewards",
            request_body=request_body,
            broadcaster_id=broadcaster_id,
        )

    def delete_custom_reward(self, broadcaster_id, id):
        "Deletes a Custom Reward on a channel."

        if "channel:manage:redemptions" not in self.session.scopes:
            raise ScopeError("<channel:manage:redemptions> scope required")
        return self.request(
            "delete",
            "/channel_points/custom_rewards",
            broadcaster_id=broadcaster_id,
            id=id,
        )

    def get_custom_reward(
        self,
        broadcaster_id: str,
        id: str = None,
        only_manageable_rewards: bool = False,
    ):
        """
        Returns a list of Custom Reward objects for the Custom Reward objects
        for the Custom Rewards on a channel.
        """

        if "channel:read:redemptions" not in self.session.scopes:
            raise ScopeError("<channel:read:redemptions> scope required")
        self.request(
            "get",
            "/channel_points/custom_rewards",
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
        sort="OLDEST",
        after: str = None,
        first: int = 20,
    ):
        """
        Returns Custom Reward Redemption objects for a Custom Reward
        on a channel that was created by the same client_id.
        """

        if "channel:read:redemptions" not in self.session.scopes:
            raise ScopeError("<channel:read:redemptions> scope required")
        return self.request(
            "get",
            "/channel_points/custom_rewards/redemptions",
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
        if "channel:manage:redemptions" not in self.sesssion.scopes:
            raise ScopeError("<channel:manage:redemptions> scope required")
        params = [
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
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
            "patch",
            "channel_points/custom_rewards",
            request_body=request_body,
            broadcaster_id=broadcaster_id,
            id=id,
        )

    def update_redemption_status(self, id, broadcaster_id: str, reward_id: str, data):
        """
        Updates the status of Custom Reward Redemption objects on a
        channel that are in the UNFULFILLED status.
        """

        assert isinstance(data, dict), "data should be a dict type"
        if "channel:manage:redemptions" not in self.session.scopes:
            raise ScopeError("<channel:manage:redemptions> scope required")
        if "status" not in data:
            raise ValueError("status key is a required body value")
        params = ["status"]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
            "patch",
            "/channel_points/custom_rewards/redemptions",
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

        return self.request("get", "/chat/emotes", broadcaster_id=broadcaster_id)

    def get_global_emotes(self):
        """
        Gets all global emotes. Global emotes are Twitch-specific emoticons
        that every user can use in Twitch chat.
        """

        return self.request("get", "/chat/emotes/global")

    def get_emote_sets(self, emote_set_id):
        "Get emotes for one or more specified emote sets."

        return self.request("get", "/chat/emotes/set", emote_set_id=emote_set_id)

    def get_global_chat_badges(self):
        """
        Get a list of chat badges that can be used in any
        chat for any channel.
        """

        return self.request("get", "/chat/badges/global")

    def get_chat_settings(self, broadcaster_id: str, moderator_id: str = None):
        "Gets the broadcaster's chat settings."

        if moderator_id is not None:
            if "moderator:read:chat_settings" not in self.session.scopes:
                raise ScopeError(
                    "<moderator:read:chat_settings> scope required if moderator_id is provided"
                )
        return self.request(
            "get",
            "/chat/settings",
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def update_chat_settings(self, broadcaster_id: str, moderator_id: str, data):
        "Updates the broadcaster's caht settings."

        assert isinstance(data, dict), "data should be a dict type"
        if "moderator:manage:chat_settings" not in self.session.scopes:
            raise ScopeError("<moderator:manage:chat_settings> scope required")
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
        return self.request(
            "patch",
            "/chat/settings",
            request_body=request_body,
            broadcaster_id=broadcaster_id,
            moderator_id=moderator_id,
        )

    def create_clip(self, broadcaster_id: str, has_delay: bool = False):
        """
        Creates a clip programmatically. This returns both an ID
        and an edit URL for the new clip.
        """

        if "clips:edit" not in self.session.scopes:
            raise ScopeError("<clips:edit> scope required")
        return self.request(
            "post", "/clips", broadcaster_id=broadcaster_id, has_delay=has_delay
        )

    def get_clips(
        self,
        broadcaster_id: str,
        game_id: str,
        id,
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

        return self.request(
            "get",
            "/clips",
            broadcaster_id=broadcaster_id,
            game_id=game_id,
            id=id,
            after=after,
            before=before,
            ended_at=ended_at,
            first=first,
            started_at=started_at,
        )

    def get_code_status(self, code, user_id: int):
        """
        Gets the status of one or more provided codes. This API requires that
        the caller is an authenticated Twitch user. The API is throttled to at
        least request per second per authenticated user.
        """

        return self.request("get", "/entitlements", code=code, user_id=user_id)

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

        return self.request(
            "get",
            "/entitlements/drops",
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

        # something perplexing about twitch's documentation here( regarding whether they are actually query params
        # or request body, their documentaion and curl usage don't match
        assert isinstance(data, dict), "data should be a dict type"
        params = ["entitlement_ids", "fulfillment_status"]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request("patch", "entitlements/drops", request_body=request_body)

    def redeem_code(self, code, user_id: int):
        "Redeems one or more redemption codes."

        return self.request("post", "/entitlements/codes", code=code, user_id=user_id)

    def get_extension_configuration_segment(
        self, broadcaster_id: str, extension_id: str, segment: str
    ):
        """
        Sets a single configuration segment of any type. The segment type is
        specified as a body parameter.
        """

        # only used when jwt's are used for authorization so need to specify that
        return self.request(
            "get",
            "/extensions/configurations",
            broadcaster_id=broadcaster_id,
            extension_id=extension_id,
            segment=segment,
        )

    def set_extension_configuration_segment(self, data):
        """
        Sets a single configuration segment of any type. The segment type
        is specified as abody parameter.
        """

        # also needs jwt authorization
        assert isinstance(data, dict), "data should be a dict type"
        params = ["extension_id", "segment", "broadcaster_id", "content", "version"]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
            "put", "/extensions/configurations", request_body=request_body
        )

    def set_extension_required_configuration(self, broadcaster_id: str, data):
        """
        Enable activation of a specified Extension, after any required broadcaster
        configuration is correct.
        """

        assert isinstance(data, dict), "data should be a dict type"
        params = ["extension_id", "extension_version", "configuration_version"]
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
            "put",
            "/extensions/required_configuration",
            request_body=request_body,
            jwt_required=True,
            broadcaster_id=broadcaster_id,
        )

    def send_extension_pubsub_message(self, data):
        """
        Forward a message using the same mechanism as the send JavaScript
        helper function.
        """

        assert isinstance(data, dict), "data should be a dict type"
        params = ["target", "broadcaster_id", "is_global_broadcast", "message"]
        for key in data.keys():
            if key not in params:
                raise InvalidRequestException(f"{key} is a required body parameter")
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
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
        activated a specific Extension.
        """

        return self.request(
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
        a version and an array of secret objects.
        """

        return self.request("get", "/extensions/jwt/secrets", jwt_required=True)

    def create_extension_secret(self, delay: int = 300):
        "Creates a JWT signing secret for a specific extension."

        return self.request(
            "post", "/extensions/jwt/secrets", jwt_required=True, delay=delay
        )

    def send_extension_chat_message(self, broadcaster_id: str, data):
        "Sends a specified chat message to a specified channel."

        assert isinstance(data, dict), "data should be a dict type"
        params = ["text", "extension_id", "extension_version"]
        for key in data.keys():
            if key not in params:
                raise InvalidRequestException(f"{key} is a required body parameter")
        request_body = {key: value for (key, value) in data.items() if key in params}
        return self.request(
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

        return self.request(
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

        return self.request(
            "get",
            "/extensions/released",
            app_or_access_token_required=True,
            extension_id=extension_id,
            extension_version=extension_version,
        )

    def get_extension_bits_products(self, should_include_all: bool = False):
        "Get a list of Bits products that belongs to an Extension."

        return self.request(
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
        return self.request(
            "put",
            "/bits/extensions",
            request_body=request_body,
            app_access_token_required=True,
        )

    def create_eventsub_subscription(self):
        "Creates an EventSub subscription."
        pass

    def delete_eventsub_subscription(self):
        "Deletes an EventSub subscription."
        pass

    def get_eventsub_subscriptions(self):
        """
        Gets a list of your EventSub subscriptions. The list is paginated
        and ordered by the oldest subscription first.
        """
        pass

    def get_top_games(self):
        """
        Gets games sorted by number of current viewers on Twitch,
        most popular first.
        """
        pass

    def get_creator_goals(self):
        "Gets the broadcaster's list of active goals."
        pass

    def get_hype_train_events(self):
        """
        Gets the information of the most recent Hype Train of the
        given channel ID.
        """
        pass

    def check_automod_status(self):
        """
        Determins whether a string message meets the channel's AutoMod
        requirements.
        """
        pass

    def manage_held_automod_messages(self):
        "Allow or deny a message that was held for review by AutoMod."
        pass

    def get_automod_settings(self):
        "Gets the broadcaster's AutoMod settings."
        pass

    def update_automod_settings(self):
        "Updates the broadcaster's AutoMod settings."
        pass

    def get_banned_events(self):
        "Return all user banned and un-banned events for a channel."
        pass

    def get_banned_users(self):
        "Returns all banned and timed-out users for a channel."
        pass

    def ban_user(self):
        """
        Bans a user from participating in a broadcaster's chat room, or puts
        them in a timeout.
        """
        pass

    def unban_user(self):
        "Removes the ban or timeout that was placed on the specified user."
        pass

    def get_blocked_terms(self):
        "Gets the broadcaster's list of non-private, blocked words or phrases."
        pass

    def add_blocked_term(self):
        "Adds a word or phrase to the broadcaster's list of blocked terms."
        pass

    def remove_blocked_term(self):
        """
        Removes the word or phrase that the broadcaster is blocking user from using
        in their chat room.
        """
        pass

    def get_moderators(self):
        "Returns all moderators in a channel."
        pass

    def get_moderator_events(self):
        """
        Returns a list of moderators or users added and removed as
        moderators from a channel.
        """
        pass

    def get_polls(self):
        """
        Get information about all polls or specific polls for a Twitch channel.
        Poll information is available for 90 days.
        """
        pass

    def create_poll(self):
        "Create a poll for a specific Twitch channel."
        pass

    def end_poll(self):
        "End a poll that is currently active."
        pass

    def get_predictions(self):
        "Get information about all Channel Points Predictions for a Twitch channel."
        pass

    def create_prediction(self):
        "Creates a Channel Points Prediction for a specific Twich channel."
        pass

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
