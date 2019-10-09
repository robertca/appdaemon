import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta

#import voluptuous as vol

# TODO: ignore tweet replies
class TrafficAnalyze(hass.Hass):
    def initialize(self):
        self.time_ranges = self.args['active_times']
        self.keywords = self.args['keywords']
        self.context_keywords = self.args['context_keywords']

        inOneMinute = datetime.now() + timedelta(minutes=1)
        interval = int(self.args['interval'])

        if interval < 1:
            raise Exception('Update interval ({}) must be at least 1 minute(s)'.format(interval))

        # delay first launch with one minute, run every 'interval' minutes
        self.run_every(self.updateState, inOneMinute, interval * 60)

    def updateState(self, kwargs):
        timeline = self.fetchTwitter()

        # Take just the first status
        status = next(iter(timeline or []), None)
        if self.processTwitterStatus(status):
            self.fire_event("Traffic", message=status['text'], title="Traffic Problem")

    def processTwitterStatus(self, status):
        # Attempt to match keywords, but with a context keyword search first
        if len(self.context_keywords) > 0:
            return ( any(keyword.lower() in status['text'].lower() for keyword in self.context_keywords) and 
                    any(keyword.lower() in status['text'].lower() for keyword in self.keywords) )

        # Attempt to match any keyword, without context
        return any(keyword.lower() in status['text'].lower() for keyword in self.keywords)

    def fetchTwitter(self):
        # Return the timeline from the sensor
        return self.get_state("sensor.twitter_parse", attribute = "timeline")
