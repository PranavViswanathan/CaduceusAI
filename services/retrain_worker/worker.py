"""
Retrain worker — polls retrain_buffer.jsonl and triggers LoRA fine-tuning
when the buffer reaches the configured minimum batch size.
"""

import logging
import os
import sys
import time

sys.path.insert(0, "/app/scripts")

import retrain_loop  # noqa: E402  (mounted via docker-compose volume)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("RETRAIN_POLL_INTERVAL_SECONDS", "300"))


def main() -> None:
    logger.info("Retrain worker started. Poll interval: %ds.", POLL_INTERVAL)
    while True:
        try:
            retrain_loop.process_buffer()
        except Exception as exc:
            logger.error("Unexpected error in retrain loop: %s", exc, exc_info=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
