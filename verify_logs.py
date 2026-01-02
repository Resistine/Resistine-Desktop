import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

from utils.logger import logger, setup_logging


def test_logging():
    # Setup logging
    setup_logging(level="DEBUG", log_to_file=True)

    logger.info("Starting logging test")
    logger.debug("This is a debug message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")

    try:
        1 / 0
    except Exception:
        logger.exception("Caught an expected division by zero")

    logger.info(
        "Logging test completed. Check console and utils/logger.py log directory."
    )


if __name__ == "__main__":
    test_logging()
