import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Split a large conversations.json into individual JSON files."
    )
    parser.add_argument("input", metavar="input_file.json", help="Input JSON export file")
    parser.add_argument("output_dir", nargs="?", help="Output directory (default: <input_dir>/split_conversations_json)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent / "split_conversations_json"
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for idx, conversation in enumerate(data):
        conv_id = conversation.get("id") or conversation.get("uuid") or f"unknown_{idx}"
        output_file = output_dir / f"{conv_id}.json"
        with output_file.open("w", encoding="utf-8") as f:
            content = json.dumps(conversation, indent=2, ensure_ascii=False)
            content = content.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
            f.write(content)
        print(f"Saved: {output_file.name}")


if __name__ == "__main__":
    main()
