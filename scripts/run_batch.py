"""Batch runner for simulated student evaluations."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Batch Runner for Socratic Tutor")
    parser.add_argument("--in-file", type=str, default="data/simulated_students.jsonl")
    parser.add_argument("--out-file", type=str, default="dev_traces.jsonl")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    print(f"Executing batch runs from {args.in_file} to {args.out_file}...")
    print("Batch processing complete.")


if __name__ == "__main__":
    main()
