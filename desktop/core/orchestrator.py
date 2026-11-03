"""
desktop/core/orchestrator.py - Application orchestrator and pipeline coordinator.

Coordinates:
- Global Hotkey -> Selection Capture -> Intent Inference -> Cloud AI (or Ollama) Generation -> UI Callbacks
- Spawns background worker threads for capture and AI inference to never block UI or listener
- Concurrency control and cancellation when user dismisses active request
- Prerequisite health check on startup
"""

import threading
from typing import Any, Callable, Optional, Union

from desktop.ai.backend_client import BackendClient
from desktop.ai.client import OllamaClient
from desktop.core.capture import SelectionCapture
from desktop.core.hotkey import HotkeyListener
from desktop.core.intents import infer_intent


class AppOrchestrator:
    """
    Central controller connecting keyboard events, text capture, intent resolution,
    AI model generation, and UI update callbacks.
    """

    def __init__(
        self,
        ai_client: Optional[Union[BackendClient, OllamaClient]] = None,
        capture: Optional[SelectionCapture] = None,
        hotkey_listener: Optional[HotkeyListener] = None,
        on_generating: Optional[Callable[[str, str, Optional[int]], None]] = None,
        on_chunk: Optional[Callable[[str, Optional[int]], None]] = None,
        on_explanation: Optional[Callable[[str, str, str, Optional[int]], None]] = None,
        on_error: Optional[Callable[[str, str, Optional[int]], None]] = None,
        on_no_selection: Optional[Callable[[Optional[int]], None]] = None,
        on_dismiss: Optional[Callable[[], None]] = None,
        on_startup_notice: Optional[Callable[[str, str], None]] = None,
        backend_manager: Optional[Any] = None,
    ):
        # Default to cloud backend client while preserving Ollama compatibility
        self.ai_client = ai_client if ai_client is not None else BackendClient()
        self.capture = capture or SelectionCapture()
        self.on_generating = on_generating
        self.on_chunk = on_chunk
        self.on_explanation = on_explanation
        self.on_error = on_error
        self.on_no_selection = on_no_selection
        self.on_dismiss = on_dismiss
        self.on_startup_notice = on_startup_notice

        # Backend lifecycle manager
        if backend_manager is not None:
            self.backend_manager = backend_manager
        elif isinstance(self.ai_client, BackendClient):
            from desktop.core.backend_manager import BackendProcessManager
            self.backend_manager = BackendProcessManager(client=self.ai_client)
        else:
            self.backend_manager = None

        # Concurrency & cancellation controls
        self._cancel_lock = threading.Lock()
        self._active_cancel_event: Optional[threading.Event] = None

        self.hotkey_listener = hotkey_listener or HotkeyListener(
            on_trigger=self._handle_hotkey_trigger,
            on_dismiss=self._handle_hotkey_dismiss,
        )

    def _handle_hotkey_trigger(self, run_id: int):
        """Dispatched from HotkeyListener; cancels any active request and starts fresh pipeline."""
        with self._cancel_lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
            cancel_event = threading.Event()
            self._active_cancel_event = cancel_event

        threading.Thread(
            target=self.process_activation,
            args=(run_id, cancel_event),
            daemon=True,
            name=f"kya-ray-activation-{run_id}",
        ).start()

    def _handle_hotkey_dismiss(self):
        """Dispatched from HotkeyListener or UI when Esc is pressed."""
        with self._cancel_lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
        if hasattr(self.hotkey_listener, "reset"):
            self.hotkey_listener.reset()
        if self.on_dismiss:
            self.on_dismiss()

    def process_activation(
        self,
        run_id: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        """
        Executes the capture and inference sequence:
        1. Captures selected text.
        2. Validates selection.
        3. Infers intent and notifies UI ('generating').
        4. Streams response chunks from AI client (or non-streaming generation).
        5. Notifies UI with result or error.
        """
        if cancel_event and cancel_event.is_set():
            return

        try:
            # Self-healing offline-to-online recovery: ensure backend is running if available
            if self.backend_manager and hasattr(self.backend_manager, "is_running"):
                try:
                    if not self.backend_manager.is_running:
                        self.backend_manager.ensure_running()
                except Exception:
                    pass

            captured_text = self.capture.capture()

            if cancel_event and cancel_event.is_set():
                return

            if not captured_text:
                if self.on_no_selection:
                    self.on_no_selection(run_id)
                return

            # Gracefully clamp very large selections to max supported length (20,000 chars)
            if len(captured_text) > 20000:
                captured_text = captured_text[:20000]

            inferred_intent = infer_intent(captured_text)

            # Notify UI to open and show 'Thinking...' with detected intent
            if self.on_generating:
                self.on_generating(captured_text, inferred_intent, run_id)

            # Check if provider supports streaming (BackendClient)
            if hasattr(self.ai_client, "stream") and self.on_chunk:
                accumulated_chunks = []
                stream_error = None

                for chunk in self.ai_client.stream(
                    captured_text, intent=inferred_intent, cancel_event=cancel_event
                ):
                    if cancel_event and cancel_event.is_set():
                        return

                    # Detect mid-stream error tokens emitted by backend client
                    if (
                        chunk.startswith("[Error:")
                        or "\n\n[Error:" in chunk
                        or chunk.startswith("Could not connect")
                        or chunk.startswith("Streaming timed out")
                        or chunk.startswith("Error during streaming:")
                        or chunk.startswith("Backend error (")
                    ):
                        stream_error = chunk.strip()
                        break

                    accumulated_chunks.append(chunk)
                    self.on_chunk(chunk, run_id)

                if cancel_event and cancel_event.is_set():
                    return

                if stream_error:
                    if self.on_error:
                        self.on_error(captured_text, stream_error, run_id)
                    return

                full_text = "".join(accumulated_chunks).strip()
                if not full_text:
                    if self.on_error:
                        self.on_error(captured_text, "No response generated by cloud backend.", run_id)
                elif self.on_explanation:
                    self.on_explanation(captured_text, full_text, inferred_intent, run_id)
            else:
                # Fallback to non-streaming generate()
                response = self.ai_client.generate(captured_text, intent=inferred_intent)
                effective_intent = getattr(response, "intent", inferred_intent)

                if cancel_event and cancel_event.is_set():
                    return

                if response.success:
                    if self.on_explanation:
                        self.on_explanation(captured_text, response.content, effective_intent, run_id)
                else:
                    if self.on_error:
                        self.on_error(captured_text, response.content, run_id)

        except Exception as error:
            print(f"[Warning] Error during activation pipeline: {error}", flush=True)
            if self.on_error and (not cancel_event or not cancel_event.is_set()):
                self.on_error("", f"Error during capture or AI request: {error}", run_id)

    def request_for_text(self, text: str, intent: str, run_id: Optional[int] = None):
        """Executes AI generation for specific text and intent in a background thread with real-time streaming and cancellation."""
        if len(text) > 20000:
            text = text[:20000]

        with self._cancel_lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
            cancel_event = threading.Event()
            self._active_cancel_event = cancel_event

        def _worker():
            try:
                if cancel_event.is_set():
                    return
                if self.on_generating:
                    self.on_generating(text, intent, run_id)

                if hasattr(self.ai_client, "stream") and self.on_chunk:
                    accumulated_chunks = []
                    stream_error = None

                    for chunk in self.ai_client.stream(text, intent=intent, cancel_event=cancel_event):
                        if cancel_event.is_set():
                            return

                        if (
                            chunk.startswith("[Error:")
                            or "\n\n[Error:" in chunk
                            or chunk.startswith("Could not connect")
                            or chunk.startswith("Streaming timed out")
                            or chunk.startswith("Error during streaming:")
                            or chunk.startswith("Backend error (")
                        ):
                            stream_error = chunk.strip()
                            break

                        accumulated_chunks.append(chunk)
                        self.on_chunk(chunk, run_id)

                    if cancel_event.is_set():
                        return

                    if stream_error:
                        if self.on_error:
                            self.on_error(text, stream_error, run_id)
                        return

                    full_text = "".join(accumulated_chunks).strip()
                    if not full_text:
                        if self.on_error:
                            self.on_error(text, "No response generated by cloud backend.", run_id)
                    elif self.on_explanation:
                        self.on_explanation(text, full_text, intent, run_id)
                else:
                    response = self.ai_client.generate(text, intent=intent)
                    if cancel_event.is_set():
                        return
                    effective_intent = getattr(response, "intent", intent)
                    if response.success:
                        if self.on_explanation:
                            self.on_explanation(text, response.content, effective_intent, run_id)
                    else:
                        if self.on_error:
                            self.on_error(text, response.content, run_id)
            except Exception as error:
                print(f"[Warning] Error during text request: {error}", flush=True)
                if self.on_error and not cancel_event.is_set():
                    self.on_error(text, f"Error: {error}", run_id)

        threading.Thread(target=_worker, daemon=True, name=f"kya-ray-request-{run_id}").start()

    def run_prerequisite_check(self):
        """Asynchronously checks if the AI backend is available."""
        def _check():
            if hasattr(self.ai_client, "check_prerequisites"):
                status, message = self.ai_client.check_prerequisites()
            elif hasattr(self.ai_client, "check_health"):
                status, message = self.ai_client.check_health()
            else:
                return

            if status != "ready" and self.on_startup_notice:
                self.on_startup_notice(status, message)

        threading.Thread(target=_check, daemon=True, name="kya-ray-prereq-check").start()

    def start(self, check_prereqs: bool = True):
        """Starts the backend manager (if applicable), hotkey listener and prerequisite check."""
        if check_prereqs and self.backend_manager:
            def _ensure_backend():
                ok, msg = self.backend_manager.ensure_running()
                if not ok and self.on_startup_notice:
                    self.on_startup_notice("offline", msg)
                elif ok:
                    self.run_prerequisite_check()
            threading.Thread(target=_ensure_backend, daemon=True, name="kya-ray-backend-ensure").start()
        elif check_prereqs:
            self.run_prerequisite_check()
        self.hotkey_listener.start()

    def stop(self):
        """Stops the hotkey listener, cancels active requests, closes client sockets, and stops owned backend."""
        with self._cancel_lock:
            if self._active_cancel_event:
                self._active_cancel_event.set()
        self.hotkey_listener.stop()
        if hasattr(self.ai_client, "close"):
            try:
                self.ai_client.close()
            except Exception as e:
                print(f"[Warning] Error closing AI client: {e}", flush=True)
        if self.backend_manager:
            try:
                self.backend_manager.stop()
            except Exception as e:
                print(f"[Warning] Error stopping backend manager: {e}", flush=True)
