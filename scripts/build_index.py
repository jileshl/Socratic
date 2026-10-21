"""Build hybrid BM25 and dense vector index from NCERT textbook passages."""

import argparse
from pathlib import Path
from socratic_tutor.index import NCERTIndex
from socratic_tutor import config


def main():
    parser = argparse.ArgumentParser(description="Build NCERT Knowledge Base Index")
    parser.add_argument("--force", action="store_true", help="Force index rebuild")
    args = parser.parse_args()

    print("Building NCERT index...")
    index = NCERTIndex()
    
    # Placeholder: populate default sample chunks for light and electricity
    sample_chunks = [
        {
            "chunk_id": "chunk_10_light_01",
            "class_num": "10",
            "subject": "Science",
            "chapter_title": "Light - Reflection and Refraction",
            "section_id": "10.2.1",
            "section_title": "Image Formation by Spherical Mirrors",
            "content": "A concave mirror produces real and inverted images except when the object is placed between the Pole (P) and Focus (F), where it forms a virtual, erect, and magnified image behind the mirror.",
            "equations": ["1/f = 1/v + 1/u", "m = -v/u"]
        },
        {
            "chunk_id": "chunk_10_electricity_01",
            "class_num": "10",
            "subject": "Science",
            "chapter_title": "Electricity",
            "section_id": "12.4",
            "section_title": "Ohm's Law",
            "content": "The potential difference, V, across the ends of a given metallic wire in an electric circuit is directly proportional to the current flowing through it, provided its temperature remains the same. V = IR.",
            "equations": ["V = I * R", "P = V * I"]
        }
    ]
    index.save(sample_chunks)
    print(f"Indexed {len(sample_chunks)} sample chunks in {config.INDEX_DIR}.")


if __name__ == "__main__":
    main()
