"""Windows system notifications — stub for platform team.

TODO: implement via winrt (winsdk) toast notifications.
Suggested approach:
    - init(): SetCurrentProcessExplicitAppUserModelID("com.resistine.desktop")
    - send(): WinRT ToastNotification from XML template
    - Add 'winsdk' to scripts/requirements/requirements-windows.txt
"""

from utils.logger import logger


def init():
    logger.debug("Windows notifications: not yet implemented")


def send(title: str, body: str, urgency: str = "normal"):
    logger.debug("Windows notification (stub): %s — %s", title, body)
