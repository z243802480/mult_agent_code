import argparse


def main():
    parser = argparse.ArgumentParser(description="A tiny greet CLI")
    parser.add_argument("name", nargs="?", default="world")
    args = parser.parse_args()
    print(f"Hello, {args.name}!")


if __name__ == "__main__":
    main()
