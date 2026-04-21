"""Stream controller for chat API responses.

Encapsulates the background-thread + queue.Queue + Tk polling pattern used
to stream OpenAI-compatible chat completions without blocking the GUI.
"""

from __future__ import annotations

import queue
import re
import threading
from typing import TYPE_CHECKING, Callable

from utils.logger import logger

if TYPE_CHECKING:
    from openai import OpenAI

_DONE = object()  # sentinel: stream finished
_CANCELLED = object()  # sentinel: stream cancelled
_POLL_MS = 50


class StreamController:
    """Manages a single streaming chat completion on a background thread.

    Callbacks (on_chunk, on_done, on_error) are always dispatched on the
    main Tk thread via ``app.after()``, so callers can safely touch widgets.
    """

    def __init__(
        self,
        app,
        on_chunk: Callable[[str], None],
        on_done: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._app = app
        self._on_chunk = on_chunk
        self._on_done = on_done
        self._on_error = on_error

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._active = False
        self._accumulated = ""
        self._poll_id: str | None = None

    # -- public API ----------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True while the stream is in progress."""
        return self._active

    def start(
        self,
        client: OpenAI,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        *,
        extra_body: dict | None = None,
        base_url: str | None = None,
    ) -> None:
        """Launch the streaming request in a daemon thread.

        *base_url* is only used for error messages (so the user sees which
        endpoint could not be reached).
        """
        if self._active:
            logger.warning("StreamController.start() called while already active")
            return

        self._active = True
        self._accumulated = ""
        self._cancel_event.clear()
        self._queue = queue.Queue()

        thread = threading.Thread(
            target=self._worker,
            args=(client, model, messages, temperature, extra_body, base_url),
            daemon=True,
        )
        thread.start()
        self._schedule_poll()

    def cancel(self) -> None:
        """Request cancellation; the thread exits and no further callbacks fire."""
        self._active = False
        self._cancel_event.set()
        self._stop_polling()

    # -- background thread ---------------------------------------------

    def _worker(
        self,
        client: OpenAI,
        model: str,
        messages: list[dict],
        temperature: float,
        extra_body: dict | None,
        base_url: str | None,
    ) -> None:
        """Run the streaming API call, pushing results into the queue."""
        try:
            kwargs: dict = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }
            if extra_body:
                kwargs["extra_body"] = extra_body

            stream = client.chat.completions.create(**kwargs)

            for chunk in stream:
                if self._cancel_event.is_set():
                    self._queue.put(("cancel", _CANCELLED))
                    return
                if chunk.choices and chunk.choices[0].delta.content:
                    self._queue.put(("chunk", chunk.choices[0].delta.content))

            self._queue.put(("done", _DONE))

        except Exception as e:
            endpoint = base_url or "https://api.openai.com/v1"
            try:
                from openai import APIConnectionError

                if isinstance(e, APIConnectionError):
                    msg = (
                        f"Could not reach {endpoint}. "
                        "Check that the host is reachable "
                        "(VPN, DNS, firewall) "
                        "and the URL in Settings is correct."
                    )
                else:
                    err = re.sub(r'sk-[A-Za-z0-9]+', 'sk-***', str(e))
                    msg = f"{err} (endpoint: {endpoint})"
            except ImportError:
                err = re.sub(r'sk-[A-Za-z0-9]+', 'sk-***', str(e))
                msg = f"{err} (endpoint: {endpoint})"

            logger.error(f"StreamController error: {msg}")
            self._queue.put(("error", msg))

    # -- main-thread polling -------------------------------------------

    def _schedule_poll(self) -> None:
        self._poll_id = self._app.after(_POLL_MS, self._poll)

    def _stop_polling(self) -> None:
        if self._poll_id is not None:
            try:
                self._app.after_cancel(self._poll_id)
            except Exception as exc:
                logger.debug(
                    f"after_cancel({self._poll_id}) failed: {exc}")
            self._poll_id = None

    def _poll(self) -> None:
        """Drain the queue and dispatch callbacks on the main thread."""
        try:
            while True:
                msg_type, data = self._queue.get_nowait()

                if msg_type == "chunk":
                    self._accumulated += data
                    if not self._cancel_event.is_set():
                        self._on_chunk(data)

                elif msg_type == "done":
                    self._active = False
                    self._on_done(self._accumulated)
                    return

                elif msg_type == "error":
                    self._active = False
                    self._on_error(data)
                    return

                elif msg_type == "cancel":
                    self._active = False
                    return

        except queue.Empty:
            pass

        if self._active and not self._cancel_event.is_set():
            self._schedule_poll()
