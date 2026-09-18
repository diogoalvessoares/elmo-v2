"""

Behaviour node.

When a head touch is detected, the behaviour updates the onboard video,
plays a sound and changes the leds.

"""

import time

import middleware as mw


LOOP_RATE = 10
TOUCH_COUNTER_THRESHOLD = 3
COOLDOWN = 2 * LOOP_RATE


class BehaviourBlush:
    """
    Middleware behaviour that triggers a "blush" animation on touch.

    Reads sleep.sleeping to select the correct video,
    then owns the display, LEDs, and speaker for the full animation.
    sleep_mode yields the display while activity.blush is True.

    > ## Attributes

    ``touch_sensors : mw.TouchSensors`` : Middleware touch sensor state used to detect head touches.

    ``leds : mw.Leds`` : Middleware LED controller for icon/animation display.

    ``onboard : mw.Onboard`` : Middleware onboard display controller for images and videos.

    ``speakers : mw.Speakers`` : Middleware speaker controller for playing sounds.

    ``behaviours : mw.Behaviours`` : Middleware behaviour configuration flags.

    ``server : mw.Server`` : Middleware server helper for resource URLs.

    ``node : mw.Node`` : Middleware node used for shutdown and logging.

    ``sleep : mw.Sleep`` : Middleware sleep state used to read current eye state.

    ``activity : mw.Activity`` : Middleware activity state used to signal display ownership.

    > ## Functions
    """

    def __init__(self):
        """
        Initialize middleware objects and behaviour node.

        > ## Parameters

        None

        > ## Returns

        None
        """
        self.touch_sensors = mw.TouchSensors()
        self.leds = mw.Leds()
        self.onboard = mw.Onboard()
        self.speakers = mw.Speakers()
        self.behaviours = mw.Behaviours()
        self.server = mw.Server()
        self.node = mw.Node("behaviour_blush")
        self.sleep = mw.Sleep()
        self.activity = mw.Activity()

    def blush(self):
        """
        Execute the full blush animation.

        Behavior
        --------
        - Reads sleep.sleeping to pick the correct transition video.
        - Sets activity.blush so sleep_mode yields the display.
        - Plays the transition video on the onboard display.
        - Simultaneously plays "love.wav" via speakers and loads
          "heartbeat.gif" into the LED matrix.
        - Waits for the video to finish, then restores open.png.
        - Restores the previous LED icon (skipping clock temporary PNGs).
        - Clears activity.blush so sleep_mode resumes.

        > ## Parameters

        None

        > ## Returns

        None
        """
        self.activity.blush = True
        self.node.loginfo("blushing")
        if self.sleep.sleeping:
            video_url = self.server.url_for_video("dark_blush_open.mp4")
            duration = 5.8
        else:
            video_url = self.server.url_for_video("open_blush_open.mp4")
            duration = 5.3

        previous_icon_url = self.leds.url
        self.onboard.video = video_url
        self.speakers.url = self.server.url_for_sound("love.wav")
        self.leds.load_from_url(self.server.url_for_icon("heartbeat.gif"))
        time.sleep(duration)
        self.onboard.image = self.server.url_for_image("normal.png")
        try:
            # Avoid restoring temporary PNG files created by the clock behaviour
            if previous_icon_url and ".png" not in previous_icon_url:
                self.leds.load_from_url(previous_icon_url)
            else:
                self.leds.clear()
        except Exception:
            self.leds.clear()
        # Release display back to sleep_mode
        self.sleep.last_interaction = time.time()
        self.activity.blush = False

    def run(self):
        """
        Main behaviour loop.

        Behavior
        --------
        - Logs startup.
        - Polls at LOOP_RATE (10 Hz).
        - Checks behaviours.blush and head touch events.
        - Uses touch count threshold and cooldown to avoid repeated triggers.
        - Calls blush() when conditions are met.
        - Always clears activity.blush and shuts down in finally block.

        > ## Parameters

        None

        > ## Returns

        None
        """
        try:
            self.node.loginfo("starting behaviour")
            touch_counter = 0
            cooldown_counter = 0
            while not self.node.is_shutdown():
                time.sleep(1.0 / LOOP_RATE)
                if cooldown_counter > 0:
                    cooldown_counter -= 1
                if self.behaviours.blush and self.touch_sensors.head_touch() and not self.behaviours.photographer:
                    if touch_counter < TOUCH_COUNTER_THRESHOLD:
                        touch_counter += 1
                    if touch_counter == TOUCH_COUNTER_THRESHOLD:
                        if cooldown_counter == 0:
                            self.blush()
                            touch_counter = 0
                            cooldown_counter = COOLDOWN
        finally:
            self.activity.blush = False
            self.node.shutdown()


if __name__ == "__main__":
    node = BehaviourBlush()
    node.run()
