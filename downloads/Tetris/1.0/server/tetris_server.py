from game_server import main

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room-id", default="1")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    # Generate random seed if not provided
    import random
    seed = args.seed if args.seed is not None else random.randint(1, 1000000)

    main(host=args.host, port=args.port, room_id=args.room_id, seed=seed)
