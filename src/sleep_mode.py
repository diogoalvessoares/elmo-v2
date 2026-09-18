"""

Tool node.

Controls the robot sleep mode state machine and onboard eye transitions.

When there is no user interaction for a configurable amount of time,
the node transitions the onboard display through open and dark
states while coordinating with behaviour nodes that may temporarily own
the display.

"""

import time
from threading import Event, Thread

from mode_manager import ModeManager
import middleware as mw


class SleepMode:
    """
    Manages the onboard display sleep transitions based on inactivity.

    Owns the onboard display during idle mode. Yields it to behaviours
    when they raise their active flag, and resumes when the flag clears.

    Behaviours read mw.Sleep().sleeping to choose the correct transition
    animation (False = eyes open, True = eyes closed).

    > ## Attributes

    ``touch : mw.TouchSensors`` : Middleware touch sensor state.

    ``display : mw.Onboard`` : Middleware onboard display controller.

    ``server : mw.Server`` : Middleware server helper for resource URLs.

    ``mode_manager : ModeManager`` : Mode manager used to determine idle and active states.

    ``sleep : mw.Sleep`` : Middleware sleep state (enabled, sleeping, timeout,
    last_activity, last_interaction).

    ``node : mw.Node`` : Middleware node helper, used for logging.

    ``activity : mw.Activity`` : Middleware activity state, used to detect behaviours
    that have temporarily taken ownership of the display.

    ``last_idle_state : bool | None`` : Last detected idle state.

    ``was_behaviour_active : bool`` : Whether a behaviour owned the display on the
    previous iteration, used to force a display refresh once it releases.

    ``wake_event : threading.Event`` : Synchronisation event used to wake the main loop.

    ``next_state : float`` : Timestamp for the next dark-mode peek animation.

    > ## Functions
    """

    def __init__(self):
        """
        Initialise middleware objects and start monitor threads.
        """
        self.touch = mw.TouchSensors()
        self.display = mw.Onboard()
        self.server = mw.Server()
        self.mode_manager = ModeManager()
        self.sleep = mw.Sleep()
        self.node = mw.Node("sleep_mode")
        self.activity = mw.Activity()

        self.sleep.last_activity = time.time()
        self.last_idle_state = None
        self.was_behaviour_active = False
        self.next_state = time.time() + self.sleep.timeout
        self.wake_event = Event()

        Thread(target=self.monitor_touch, daemon=True).start()
        Thread(target=self.monitor_mode, daemon=True).start()

    def monitor_touch(self):
        """
        Background thread: resets the activity timer on a new chest touch
        and wakes the main loop immediately.

        Only chest touches are handled here. Head touches are exclusively
        used by behaviour_blush — reacting to them here would cause
        sleep_mode to call eyes_opening() at the same time blush fires,
        creating a display race condition.
        """
        last_touch = False
        while True:
            touched = self.touch.touch_chest
            if touched and not last_touch:
                self.sleep.last_activity = time.time()
                self.wake_event.set()
            last_touch = touched
            time.sleep(0.1)

    def monitor_mode(self):
        """
        Background thread: resets the activity timer on idle/non-idle
        transitions caused by other behaviours becoming active or inactive,
        and when a behaviour explicitly signals interaction via
        mw.Sleep().last_interaction.
        """
        last_interaction = 0.0
        while True:
            idle = self.is_idle_mode()
            if idle != self.last_idle_state:
                self.last_idle_state = idle
                self.sleep.last_activity = time.time()
                self.wake_event.set()
            try:
                t = self.sleep.last_interaction
                if t > last_interaction:
                    last_interaction = t
                    self.sleep.last_activity = t
                    self.wake_event.set()
            except TypeError:
                pass
            time.sleep(0.2)

    def is_idle_mode(self):
        """
        Check whether the robot is currently in idle mode.

        Returns
        -------
        bool
            True if no active non-idle behaviour is running.
        """
        b = self.mode_manager.behaviours
        return not (
            b.conversation or
            b.photographer or
            b.akinator or
            b.wifi_connect
        )

    def eyes_closing(self):
        """
        Transition from open eyes to fully dark screen.

        Plays open_dark.webm and waits for the browser to confirm playback
        has ended. The video already ends on the dark frame so no image
        restore is needed. Publishes sleeping=True.
        No-op if already sleeping.
        """
        if self.sleep.sleeping:
            return
        self.display.video = self.server.url_for_video("open_dark.webm")
        while self.display.video is not None:
            time.sleep(0.05)
        self.sleep.sleeping = True

    def eyes_opening(self):
        """
        Wake from dark to open eyes.

        Plays dark_open.webm, waits for playback to finish, then restores
        the open static image. Publishes sleeping=False and resets the
        activity timer.
        """
        self.display.video = self.server.url_for_video("dark_open.webm")
        while self.display.video is not None:
            time.sleep(0.05)
        self.display.image = self.server.url_for_image("normal.png")
        self.sleep.sleeping = False
        self.sleep.last_activity = time.time()

    def eyes_look_around(self):
        """
        While in the dark state, play a spontaneous peek animation
        at the configured sleep interval, then return to the dark
        static image.

        Does nothing if a behaviour owns the display, or if it is too soon.
        If a behaviour becomes active mid-playback, the dark restore is skipped
        so it does not clobber the behaviour's animation.
        """
        if time.time() < self.next_state:
            return
        if self.activity.blush or self.activity.hello:
            return
        self.display.video = self.server.url_for_video("dark_squint_dark.webm")
        while self.display.video is not None:
            time.sleep(0.05)
        if not (self.activity.blush or self.activity.hello):
            self.display.image = self.server.url_for_image("background_black.png")
        self.next_state = time.time() + self.sleep.timeout

    def run(self):
        """
        Main loop.

        Priority order each iteration:
        1. Yield the display while any behaviour is active.
        2. Idle path:
            - Touch while dark → eyes_opening.
            - Inactive >= configured timeout → dark screen; spontaneous peeks.
            - Otherwise → open eyes (static PNG).
        3. Non-idle path: restore open eyes and reset timer.

        Uses wake_event to avoid busy-waiting; timeout is 1 second.
        """
        while True:
            behaviour_active = self.activity.blush or self.activity.hello
            if not self.sleep.enabled:
                if self.sleep.sleeping:
                    self.eyes_opening()
                self.wake_event.wait(timeout=1.0)
                self.wake_event.clear()
                continue
            if behaviour_active:
                self.was_behaviour_active = True
                self.wake_event.wait(timeout=0.1)
                self.wake_event.clear()
                continue
            if self.was_behaviour_active:
                self.was_behaviour_active = False
                self.display.image = self.server.url_for_image("normal.png")
            inactive_time = time.time() - self.sleep.last_activity

            if self.is_idle_mode():
                touched = self.touch.touch_chest
                if touched and self.sleep.sleeping:
                    self.eyes_opening()
                elif inactive_time >= self.sleep.timeout:
                    if not self.sleep.sleeping:
                        self.eyes_closing()
                        self.next_state = time.time() + self.sleep.timeout
                    else:
                        self.eyes_look_around()
                else:
                    if self.sleep.sleeping:
                        self.display.image = self.server.url_for_image("normal.png")
                        self.sleep.sleeping = False
                    else:
                        self.display.image = self.server.url_for_image("normal.png")
            else:
                if self.sleep.sleeping:
                    self.eyes_opening()
                else:
                    self.display.image = self.server.url_for_image("normal.png")
                self.sleep.last_activity = time.time()

            self.wake_event.wait(timeout=1.0)
            self.wake_event.clear()


if __name__ == "__main__":
    node = SleepMode()
    node.run()
