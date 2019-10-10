import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta
import tweepy

from constants import (
    CONF_TWITTER_KEY,
    CONF_TWITTER_SECRET,
    CONF_TWITTER_ACCESS_TOKEN_SECRET,
    CONF_TWITTER_ACCESS_TOKEN,
    CONF_TWITTER_USER,
    CONF_DEBUG,
    CONF_INTERVAL
)

CONF_KEYWORDS = 'keywords'
CONF_CONTEXT_KEYWORDS = 'context_keywords'

import voluptuous as vol

def ListLenMod2(value):
    if isinstance(value, list) and len(value) % 2 == 0:
        return value
    raise vol.Invalid("Not a list with even number of items")

APP_SCHEMA = vol.Schema({
    vol.Required(CONF_CONTEXT_KEYWORDS): list,
    vol.Required(CONF_KEYWORDS): list,
    vol.Required("notification_ranges"): ListLenMod2,
    vol.Required(CONF_INTERVAL): vol.All(int, vol.Range(min=1)),
    vol.Required(CONF_TWITTER_ACCESS_TOKEN): str,
    vol.Required(CONF_TWITTER_KEY): str,
    vol.Required(CONF_TWITTER_SECRET): str,
    vol.Required(CONF_TWITTER_ACCESS_TOKEN_SECRET): str,
    vol.Required(CONF_TWITTER_USER): str,
    vol.Optional(CONF_DEBUG,default=False): bool
}, extra=vol.ALLOW_EXTRA)

class TrafficAnalyze(hass.Hass):
    APP_SCHEMA = APP_SCHEMA

    def initialize(self):
        # Check if the app configuration is correct:
        try:
            self.APP_SCHEMA(self.args)
        except vol.Invalid as err:
            raise Exception("Invalid app setting: " + str(err))

        inOneMinute = datetime.now() + timedelta(minutes=1)
        interval = int(self.args['interval'])

        self.time_ranges = self.args['notification_ranges']
        self.keywords = self.args.get(CONF_KEYWORDS, {})
        self.context_keywords = self.args.get(CONF_CONTEXT_KEYWORDS, {})
        self.twitter_user = self.args.get(CONF_TWITTER_USER)
        # hardcoded for now to avoid rate limiting
        self.num_timeline_entries = 5 #min(30, num_timeline_entries)
        self.twitter_since_id = None

        consumer_key = self.args.get(CONF_TWITTER_KEY)
        consumer_secret = self.args.get(CONF_TWITTER_SECRET)
        access_token = self.args.get(CONF_TWITTER_ACCESS_TOKEN)
        access_secret = self.args.get(CONF_TWITTER_ACCESS_TOKEN_SECRET)

        if consumer_key and consumer_secret:
            self.auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
            self.auth.set_access_token(access_token, access_secret)
        else:
            self.auth = None
        
        if self.auth is None:
            raise Exception("Could not connect to Twitter API")

        self.api = tweepy.API(self.auth)

        if 'debug' in self.args and self.args['debug']:
            inOneMinute = datetime.now()
            interval = 2
            self.time_ranges = []

        # delay first launch with one minute, run every 'interval' minutes
        self.run_every(self.updateState, inOneMinute, interval * 60)

    def updateState(self, kwargs):
        valid = []
        for p in zip(self.time_ranges[::2], self.time_ranges[1::2]):
            range_start = datetime.strptime(p[0], '%H:%M').time()
            range_end = datetime.strptime(p[1], '%H:%M').time()
            valid.append( self.time_in_range(range_start, range_end, datetime.now().time()) )
        if len(valid) > 0 and not any(valid):
            return

        self.updateTwitterTimeline()

        # Take just the first status
        status = next(iter(self.timeline or []), None)
        if status != None and self.processTwitterStatus(status):
            self.fire_event("Traffic", message=status['text'], title="Traffic Problem")

    def processTwitterStatus(self, status):
        # Attempt to match keywords, but with a context keyword search first
        if len(self.context_keywords) > 0:
            return ( any(keyword.lower() in status['text'].lower() for keyword in self.context_keywords) and 
                    any(keyword.lower() in status['text'].lower() for keyword in self.keywords) )

        # Attempt to match any keyword, without context
        return any(keyword.lower() in status['text'].lower() for keyword in self.keywords)

    def updateTwitterTimeline(self):
        """Get the latest data from the source and update the state."""

        user = self.api.get_user(self.twitter_user)
        if (user == None):
            self.error("Unable to retrieve data from twitter api")
            return

        try:
            self.timeline = []

            # Iterate through the first N statuses in the home timeline
            for status in tweepy.Cursor(self.api.user_timeline, id=self.twitter_user, since_id=self.twitter_since_id, count=self.num_timeline_entries).items(self.num_timeline_entries):
                self.twitter_since_id = max(self.twitter_since_id or 0, status.id)
                if status.in_reply_to_status_id != None:
                    continue

                processed_status = {
                    "text": status.text,
                    "url": "https://twitter.com/%s/status/%s" % (status.user.screen_name, status.id),
                    "posted_at": str(status.created_at),
                    "id": status.id_str,
                    "in_reply_to": status.in_reply_to_status_id_str
                }

                self.timeline.append(processed_status)
        except tweepy.RateLimitError:
            self.error("Unable to parse data due to Twitter Rate Limiting")
            return
        except tweepy.TweepError as te:
            self.error("Unable to parse data due to API Error: " + str(te))
            return
        except Exception as e:
            self.error("Unable to extract data from Twitter: " + str(e))
            return

    def time_in_range(self, start, end, x):
        """Return true if x is in the range [start, end]"""
        if start <= end:
            return start <= x <= end
        else:
            return start <= x or x <= end
