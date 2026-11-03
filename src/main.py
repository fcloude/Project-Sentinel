import time

from src.app_logging import get_logger
from src.engine.engine import SentinelEngine

logger = get_logger(__name__)

# Creating the engine is instant: AI models load when you press Start.
engine = SentinelEngine()


if __name__ == "__main__":
    engine.start()

    try:
        while engine.running:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
        engine.stop()
