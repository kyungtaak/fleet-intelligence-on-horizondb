import asyncio
import os
import selectors
import sys

import uvicorn


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        loop="app.server:selector_loop_factory" if sys.platform == "win32" else "auto",
    )


if __name__ == "__main__":
    main()