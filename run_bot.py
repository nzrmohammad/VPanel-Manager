import sys
import os
import logging
from bot.custom_bot import HiddifyBot, setup_bot_logging

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

if __name__ == "__main__":
    setup_bot_logging()

    logger = logging.getLogger(__name__)
    logger.info("Starting bot instance...")

    bot_instance = HiddifyBot()
    try:
        bot_instance.start()
    except Exception as e:
        logger.critical(f"Bot failed to start from run_bot.py: {e}", exc_info=True)
