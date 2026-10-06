"""Run the independent durable reminder worker; outward channels default disabled.

python -m scripts.run_reminders --once --env-file .env
python -m scripts.run_reminders --loop --env-file .env
"""

import argparse
import json
import signal
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--env-file")
    parser.add_argument("--interval", type=int, default=30)
    args = parser.parse_args()
    if not 5 <= args.interval <= 60:
        parser.error("interval must be between 5 and 60 seconds")
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    from app.db import init_db
    from app.services.notification_worker import tick

    init_db()
    instance = str(uuid4())
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopped:
        print(json.dumps(tick(instance)), flush=True)
        if args.once:
            break
        # Sleep in short pieces so supervisor termination is prompt.
        for _ in range(args.interval):
            if stopped:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
