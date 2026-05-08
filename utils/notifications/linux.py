"""Linux system notifications — stub for platform team.

TODO: implement via notify-send (libnotify) subprocess.
Suggested approach:
    subprocess.Popen(["notify-send", "--app-name=Resistine",
                      f"--urgency={urgency}", title, body],
                     stdout=DEVNULL, stderr=DEVNULL)
"""

from utils.logger import logger


def init():
    logger.debug("Linux notifications: not yet implemented")


def send(title: str, body: str, urgency: str = "normal"):
    logger.debug("Linux notification (stub): %s — %s", title, body)
