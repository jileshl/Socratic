"""Start the Socratic Tutor web service (student view, teacher view, /metrics).

    python -m socratic_tutor.app          # http://127.0.0.1:8000
    make app                              # same
"""

import os


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"Socratic Tutor: student view http://{host}:{port}/  ·  teacher view http://{host}:{port}/teacher")
    uvicorn.run("socratic_tutor.web.server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
